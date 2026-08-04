import asyncio
import base64
import threading
import time
import uuid
from typing import Any, Dict, List, Optional
from UIProvider import UIProvider

class PendingRequest:
    def __init__(self,request_id: str,prompt: str, data_type: type, kind: str = "request_data", meta: Optional[dict] = None,):
        self.request_id = request_id
        self.prompt = prompt
        self.data_type = data_type
        self.kind = kind
        self.meta = meta or {}
        self.created_at = time.time()
        self.event = threading.Event()
        self.value: Any = None

class ConnectionManager:
    def __init__(self):
        self.active_websockets: List[Any] = []
        self._lock = threading.Lock()

    async def connect(self, websocket):
        await websocket.accept()
        with self._lock:
            self.active_websockets.append(websocket)

    def disconnect(self, websocket):
        with self._lock:
            if websocket in self.active_websockets:
                self.active_websockets.remove(websocket)

    async def broadcast(self, payload: dict):
        with self._lock:
            connections = list(self.active_websockets)
        dead = []
        for ws in connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            with self._lock:
                for ws in dead:
                    if ws in self.active_websockets:
                        self.active_websockets.remove(ws)

class WebUIProvider(UIProvider):
    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.manager = ConnectionManager()
        self._lock = threading.Lock()
        self.pending_requests: Dict[str, PendingRequest] = {}
        self.status_history: List[dict] = []
        self.message_history: List[dict] = []
        self.ready_event = threading.Event()
        self.ping_timeout_event = threading.Event()
        self.disconnect_event = threading.Event()
        self._max_history = 500

    def attach_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def reset_session_state(self):
        with self._lock:
            self.pending_requests.clear()
            self.status_history.clear()
            self.message_history.clear()
        self.ready_event.clear()
        self.ping_timeout_event.clear()
        self.disconnect_event.clear()

    def _schedule_broadcast(self, payload: dict):
        if self.loop is None or self.loop.is_closed():
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self.loop:
            self.loop.create_task(self.manager.broadcast(payload))
        else:
            asyncio.run_coroutine_threadsafe(self.manager.broadcast(payload), self.loop)

    def _trim(self, arr: list):
        if len(arr) > self._max_history:
            del arr[: len(arr) - self._max_history]

    def _add_status(self, stage: str, message: str, status_type: str):
        payload = {
            "type": "status",
            "stage": stage,
            "message": message,
            "status_type": status_type,
            "ts": time.time()
        }

        with self._lock:
            self.status_history.append(payload)
            self._trim(self.status_history)
        self._schedule_broadcast(payload)

    def _add_message(self, direction: str, text: str, timestamp: Optional[int] = None):
        payload = {
            "type": "message",
            "direction": direction,
            "timestamp": timestamp if timestamp is not None else int(time.time()),
            "text": text,
            "ts": time.time()
        }

        with self._lock:
            self.message_history.append(payload)
            self._trim(self.message_history)
        self._schedule_broadcast(payload)

    def update_status(self, stage: str, message: str, status_type: str = "in_progress"):
        self._add_status(stage, message, status_type)

    def on_text_received(self, timestamp: int, text: str):
        self._add_message("incoming", text, timestamp)

    def record_outgoing_message(self, text: str):
        self._add_message("outgoing", text, int(time.time()))

    def request_data(self, prompt: str, data_type: type):
        return self._wait_for_user_response(kind="request_data",prompt=prompt, data_type=data_type, meta={})

    def check_signatures(self, my_sign: str, companion_sign: str) -> bool:
        prompt = f"Check signatures: mine={my_sign}, companion={companion_sign}"
        meta = {
            "my_sign": my_sign,
            "companion_sign": companion_sign
        }

        result = self._wait_for_user_response(kind="check_signatures",prompt=prompt,data_type=bool,meta=meta)
        return bool(result)

    def on_ready(self):
        self.ready_event.set()
        self._add_status("CryptoLayer", "Ready", "success")
        self._schedule_broadcast({"type": "ready", "ts": time.time()})

    def on_ping_timeout(self):
        self.ping_timeout_event.set()
        self._add_status("CryptoLayer", "Ping timeout", "error")
        self._schedule_broadcast({"type": "ping_timeout", "ts": time.time()})

    def on_disconnect(self):
        self.disconnect_event.set()
        self._add_status("CryptoLayer", "Disconnected", "error")
        self._schedule_broadcast({"type": "disconnect", "ts": time.time()})

    def _wait_for_user_response(self,kind: str, prompt: str, data_type: type, meta: dict, timeout: Optional[float] = None):
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is not None:
            raise RuntimeError("Blocking UI request must be called from a worker thread, " "not from the asyncio event loop thread.")
        request_id = uuid.uuid4().hex
        pending = PendingRequest(request_id=request_id, prompt=prompt, data_type=data_type, kind=kind, meta=meta)
        with self._lock:
            self.pending_requests[request_id] = pending

        payload = {
            "type": kind,
            "request_id": request_id,
            "prompt": prompt,
            "data_type": getattr(data_type, "__name__", str(data_type)),
            "meta": meta,
            "ts": time.time()
        }

        self._schedule_broadcast(payload)
        answered = pending.event.wait(timeout)
        if not answered:
            with self._lock:
                self.pending_requests.pop(request_id, None)
            raise TimeoutError(f"No answer for UI request {request_id}")

        return pending.value

    def answer_request(self, request_id: str, raw_value: Any):
        with self._lock:
            pending = self.pending_requests.get(request_id)
            if pending is None:
                raise KeyError(request_id)
            pending.value = self._coerce_value(raw_value, pending.data_type)
            pending.event.set()
            self.pending_requests.pop(request_id, None)

    def get_pending_requests(self) -> List[dict]:
        with self._lock:
            return [
                {
                    "request_id": req.request_id,
                    "kind": req.kind,
                    "prompt": req.prompt,
                    "data_type": getattr(req.data_type, "__name__", str(req.data_type)),
                    "meta": req.meta,
                    "created_at": req.created_at,
                }
                for req in self.pending_requests.values()
            ]

    def get_history(self, limit: int = 100) -> List[dict]:
        with self._lock:
            return self.message_history[-limit:]

    def get_statuses(self, limit: int = 100) -> List[dict]:
        with self._lock:
            return self.status_history[-limit:]

    def get_state(self) -> dict:
        with self._lock:
            pending_count = len(self.pending_requests)

        return {
            "ready": self.ready_event.is_set(),
            "ping_timeout": self.ping_timeout_event.is_set(),
            "disconnected": self.disconnect_event.is_set(),
            "pending_requests": pending_count,
        }

    @staticmethod
    def _coerce_value(raw_value: Any, data_type: type) -> Any:
        if data_type is bool:
            if isinstance(raw_value, bool):
                return raw_value
            if isinstance(raw_value, (int, float)):
                return bool(raw_value)
            if isinstance(raw_value, str):
                return raw_value.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "y",
                    "ok",
                    "on",
                    "trust",
                    "trusted",
                }

            return bool(raw_value)

        if data_type is int:
            return int(raw_value)
        if data_type is float:
            return float(raw_value)
        if data_type is str:
            return str(raw_value)
        if data_type is bytes:
            if raw_value is None:
                return b""
            if isinstance(raw_value, str):
                return base64.b64decode(raw_value)
            if isinstance(raw_value, (bytes, bytearray)):
                return bytes(raw_value)
            if isinstance(raw_value, list):
                return bytes(raw_value)

            return str(raw_value).encode("utf-8")

        return raw_value
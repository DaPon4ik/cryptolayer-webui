import sys
import os
from pathlib import Path
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = Path(sys._MEIPASS)
    APP_DIR = Path(os.path.dirname(sys.executable))
else:
    BUNDLE_DIR = Path(__file__).parent
    APP_DIR = BUNDLE_DIR
sys.path.insert(0, str(BUNDLE_DIR))
STATIC_DIR = BUNDLE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
MODULES_DIR = BUNDLE_DIR / "modules"
IMAGES_DIR = STATIC_DIR / "images"
IMAGES_DIR.mkdir(exist_ok=True)
import asyncio
import importlib
import inspect
import json
import queue
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request,Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))

from base_module import BaseModule
from crypto_layer import CryptoLayer
from web_ui_provider import WebUIProvider
from http_module import HTTPModule

if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(sys._MEIPASS)
    APP_DIR = Path(os.path.dirname(sys.executable))
else:
    BUNDLE_DIR = Path(__file__).parent
    APP_DIR = BUNDLE_DIR

STATIC_DIR = BUNDLE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

MODULES_DIR = BUNDLE_DIR / "modules"
def resolve_data_dir(data_dir: str) -> str:
    p = Path(data_dir)
    if p.is_absolute():
        return str(p)
    return str((APP_DIR / p).resolve())

def scan_modules() -> List[BaseModule]:
    found = []
    if not MODULES_DIR.is_dir():
        return found

    for item in sorted(os.listdir(MODULES_DIR)):
        item_path = MODULES_DIR / item
        if item_path.is_dir() and not item.startswith("_"):
            try:
                mod = importlib.import_module(f"modules.{item}.main")
            except Exception as e:
                print(f"[modules] skip '{item}': {e}")
                continue
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if issubclass(obj, BaseModule) and obj is not BaseModule:
                    try:
                        found.append(obj())
                    except Exception as e:
                        print(f"[modules] cannot instantiate {obj.__name__}: {e}")
    return found

MODULES: List[BaseModule] = [HTTPModule()] + scan_modules()

def find_module(unique_id: str) -> Optional[BaseModule]:
    for m in MODULES:
        if m.unique_id == unique_id:
            return m
    return None

ui_provider = WebUIProvider()
crypto: Optional[CryptoLayer] = None
crypto_lock = threading.Lock()
init_state_lock = threading.Lock()
init_state = {
    "status": "not_initialized",
    "error": None,
    "started_at": None,
    "module": None
}

def set_init_state(status: str, error: Optional[str] = None, module: Optional[str] = None):
    with init_state_lock:
        init_state["status"] = status
        init_state["error"] = error
        if module is not None:
            init_state["module"] = module
        if status == "initializing":
            init_state["started_at"] = time.time()

def get_init_state() -> dict:
    with init_state_lock:
        return dict(init_state)

def default_wordcoder_dict() -> Dict[str, str]:
    return {f"{i:02x}": f"word{i:03d}" for i in range(256)}


def reset_stop_events():
    try:
        from levels.base import Base
        if hasattr(Base, "stop_event") and hasattr(Base.stop_event, "clear"):
            Base.stop_event.clear()
    except Exception:
        pass
    try:
        from base_module import BaseModule as BM
        if hasattr(BM, "stop_event") and hasattr(BM.stop_event, "clear"):
            BM.stop_event.clear()
    except Exception:
        pass

class InitRequest(BaseModel):
    data_dir: str = "./data"
    password: str
    wordcoder_dict: Optional[Dict[str, str]] = None
    module_id: str = "web.http_module"
    credentials: List[str] = []
    companion_user_id: Optional[str] = None

class SendTextRequest(BaseModel):
    text: str

class AnswerRequestBody(BaseModel):
    request_id: str
    value: Optional[Any] = None
    approved: Optional[bool] = None
    trusted: Optional[bool] = None

class InboxPayload(BaseModel):
    data: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    ui_provider.attach_loop(asyncio.get_running_loop())
    yield
    if crypto is not None and getattr(crypto, "APPLICATION_LEVEL", None) is not None:
        threading.Thread(target=crypto.stop, kwargs={"send_disconnect": False},daemon=True).start()

app = FastAPI(title="CryptoLayer Web Wrapper", lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
IMAGES_DIR = STATIC_DIR / "images"
IMAGES_DIR.mkdir(exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="static/index.html not found")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

@app.get("/api/modules")
async def list_modules():
    items = []
    for m in MODULES:
        items.append(
            {
                "unique_id": m.unique_id,
                "name": m.name,
                "description": m.description,
                "credentials": m.get_creds(),
                "is_http": isinstance(m, HTTPModule)
            }
        )
    return {"items": items}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ui_provider.manager.connect(websocket)
    try:
        await websocket.send_json(
            {
                "type": "bootstrap",
                "init_state": get_init_state(),
                "ui_state": ui_provider.get_state(),
                "pending_requests": ui_provider.get_pending_requests(),
                "statuses": ui_provider.get_statuses(100),
                "history": ui_provider.get_history(100)
            }
        )
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "answer":
                request_id = msg.get("request_id")
                if request_id is not None:
                    request_id = str(request_id)
                value = msg.get("value")
                if value is None:
                    if msg.get("approved") is not None:
                        value = msg.get("approved")
                    elif msg.get("trusted") is not None:
                        value = msg.get("trusted")
                if request_id:
                    try:
                        ui_provider.answer_request(request_id, value)
                    except KeyError:
                        pass
                    except Exception:
                        pass
    except WebSocketDisconnect:
        ui_provider.manager.disconnect(websocket)
    except Exception:
        ui_provider.manager.disconnect(websocket)

@app.get("/api/state")
async def state():
    return {
        "init_state": get_init_state(),
        "ui_state": ui_provider.get_state(),
        "module": {
            "ready": HTTPModule.is_ready(),
            "outbox_size": HTTPModule.outbox_queue.qsize()
        },
        "crypto": {
            "initialized": crypto is not None,
            "node_id": crypto.NODE_ID if crypto is not None else None,
            "companion_node_id": crypto.COMPANION_NODE_ID if crypto is not None else None
        },
    }


@app.post("/api/init")
async def init(payload: InitRequest):
    global crypto
    module = find_module(payload.module_id)
    if module is None:
        raise HTTPException(status_code=404, detail=f"Module '{payload.module_id}' not found")
    if not isinstance(module, HTTPModule):
        if len(payload.credentials) < len(module.expected_credentials):
            raise HTTPException(status_code=422,detail=f"Module '{module.name}' requires credentials: {[c.name for c in module.expected_credentials]}")
        if not payload.companion_user_id:
            raise HTTPException(status_code=422, detail=f"Module '{module.name}' requires companion user_id")
    with crypto_lock:
        current_status = get_init_state()["status"]
        if current_status in {"initializing", "ready"}:
            raise HTTPException(status_code=409, detail=f"CryptoLayer is already {current_status}")
        set_init_state("initializing", module=module.name)
    if isinstance(module, HTTPModule):
        HTTPModule.reset()

    ui_provider.reset_session_state()
    reset_stop_events()
    module.init(payload.credentials, payload.companion_user_id or "")
    wordcoder_dict = payload.wordcoder_dict or default_wordcoder_dict()

    def run_init():
        global crypto
        try:
            crypto = CryptoLayer(ui_provider=ui_provider, data_dir=resolve_data_dir(payload.data_dir),module_class=module,password=payload.password, wordcoder_dict=wordcoder_dict)
            crypto.init()
            set_init_state("ready", module=module.name)
        except Exception as exc:
            crypto = None
            set_init_state("error", str(exc), module=module.name)
    threading.Thread(target=run_init, daemon=True).start()

    return {"ok": True, "status": "initialization_started", "module": module.name} 


@app.post("/api/stop")
async def stop():
    if crypto is None:
        raise HTTPException(status_code=400, detail="CryptoLayer is not initialized")
    set_init_state("stopping")
    def run_stop():
        try:
            if getattr(crypto, "APPLICATION_LEVEL", None) is not None:
                crypto.stop(send_disconnect=True)
            set_init_state("stopped")
        except Exception as exc:
            set_init_state("error", str(exc))
    threading.Thread(target=run_stop, daemon=True).start()

    return {"ok": True, "status": "stopping"}

@app.post("/api/messages/send")
async def send_message(payload: SendTextRequest):
    if crypto is None:
        raise HTTPException(status_code=409, detail="CryptoLayer is not initialized")
    if get_init_state()["status"] != "ready":
        raise HTTPException(status_code=409, detail="CryptoLayer is not ready")
    if ui_provider.disconnect_event.is_set() or ui_provider.ping_timeout_event.is_set():
        raise HTTPException(status_code=409, detail="Connection is not available")
    try:
        await asyncio.to_thread(crypto.send, payload.text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Send failed: {exc}")
    ui_provider.record_outgoing_message(payload.text)

    return {"ok": True}

@app.get("/api/messages/history")
async def messages_history(limit: int = Query(100, ge=1, le=1000)):
    return {"items": ui_provider.get_history(limit)}

@app.get("/api/statuses")
async def statuses(limit: int = Query(100, ge=1, le=1000)):
    return {"items": ui_provider.get_statuses(limit)}

@app.get("/api/ui/requests")
async def ui_requests():
    return {"items": ui_provider.get_pending_requests()}

@app.post("/api/ui/answer")
async def ui_answer(payload: AnswerRequestBody):
    value = payload.value
    if value is None and payload.approved is not None:
        value = payload.approved
    if value is None and payload.trusted is not None:
        value = payload.trusted
    try:
        ui_provider.answer_request(payload.request_id, value)
    except KeyError:
        raise HTTPException(status_code=404, detail="Request not found")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid value: {exc}")

    return {"ok": True}

@app.get("/api/keys")
async def keys():
    if crypto is None:
        raise HTTPException(status_code=400, detail="CryptoLayer is not initialized")

    result = {
        "node_id": crypto.NODE_ID,
        "companion_node_id": crypto.COMPANION_NODE_ID,
        "encryption_ready": crypto.AES_KEY is not None,
        "my_signature_fingerprint": None,
        "companion_signature_fingerprint": None
    }

    if crypto.SIGN_PUBLIC_KEY is not None:
        try:
            result["my_signature_fingerprint"] = crypto.get_firts_last_4_chars_sign(crypto.SIGN_PUBLIC_KEY)
        except Exception:
            pass

    if crypto.COMPANION_SIGN is not None:
        try:
            result["companion_signature_fingerprint"] = crypto.get_firts_last_4_chars_sign(crypto.COMPANION_SIGN)
        except Exception:
            pass

    return result


@app.get("/api/keys/known-nodes")
async def known_nodes():
    if crypto is None:
        raise HTTPException(status_code=400, detail="CryptoLayer is not initialized")
    path = crypto.KNOWN_NODES_DIR_PATH
    if not os.path.isdir(path):
        return {"items": []}
    items = []
    for name in os.listdir(path):
        full_path = os.path.join(path, name)
        if os.path.isfile(full_path):
            items.append({"node_id": name, "size": os.path.getsize(full_path)})

    return {"items": items}


@app.delete("/api/keys/known-nodes/{node_id}")
async def delete_known_node(node_id: str):
    if crypto is None:
        raise HTTPException(status_code=400, detail="CryptoLayer is not initialized")
    safe_name = os.path.basename(node_id)
    path = os.path.join(crypto.KNOWN_NODES_DIR_PATH, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Known node not found")
    os.remove(path)

    return {"ok": True}

@app.post("/http-module/inbox")
async def http_module_inbox(payload: InboxPayload):
    if not HTTPModule.is_ready():
        raise HTTPException(status_code=409, detail="HTTPModule is not ready")
    HTTPModule.inbox_queue.put(payload.data)

    return {"ok": True}

@app.post("/http-module/inbox/raw")
async def http_module_inbox_raw(request: Request):
    if not HTTPModule.is_ready():
        raise HTTPException(status_code=409, detail="HTTPModule is not ready")
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=422, detail="Empty body")
    HTTPModule.inbox_queue.put(raw.decode("utf-8"))

    return {"ok": True}


@app.get("/http-module/outbox")
async def http_module_outbox(timeout: float = Query(0, ge=0, le=30), max_items: int = Query(100, ge=1, le=1000)):
    items = []
    if timeout > 0:
        try:
            item = await asyncio.wait_for(asyncio.to_thread(HTTPModule.outbox_queue.get, True, timeout),timeout=timeout + 1.0,)
            items.append(item)
        except (asyncio.TimeoutError, queue.Empty):
            pass
    while len(items) < max_items:
        try:
            items.append(HTTPModule.outbox_queue.get_nowait())
        except queue.Empty:
            break

    return {"items": [{"ts": i.get("ts"), "data": i.get("data")} for i in items], "count": len(items)}


@app.get("/http-module/outbox/raw")
async def http_module_outbox_raw(timeout: float = Query(0, ge=0, le=30),):
    try:
        if timeout > 0:
            item = await asyncio.wait_for(asyncio.to_thread(HTTPModule.outbox_queue.get, True, timeout), timeout=timeout + 1.0)
        else:
            item = HTTPModule.outbox_queue.get_nowait()
    except (asyncio.TimeoutError, queue.Empty):

        return Response(status_code=204)

    return Response(content=item.get("data", ""), media_type="text/plain; charset=utf-8")
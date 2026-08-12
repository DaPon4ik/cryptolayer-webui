import queue
import threading
import time

from base_module import BaseModule, Credential


class HTTPModule(BaseModule):
    expected_credentials = [
        Credential("n", "n")
    ]
    outbox_queue = queue.Queue()
    inbox_queue = queue.Queue()
    session_ready = threading.Event()

    @property
    def unique_id(self):
        return "web.http_module"

    @property
    def name(self):
        return "*нейм*"

    @property
    def description(self):
        return "тест по локалке"

    class Sender(BaseModule.Sender):
        def __init__(self, credentials, user_id):
            super().__init__(credentials, user_id)

        def send(self, text: str):
            HTTPModule.outbox_queue.put({"data": text, "ts": time.time()})

    class Listener(BaseModule.Listener):
        def __init__(self, credentials, ingester, user_id, stop_event):
            super().__init__(credentials, ingester, user_id, stop_event)

        def listen(self) -> str:
            while not self.stop_event.is_set():
                try:
                    data = HTTPModule.inbox_queue.get(timeout=1.0)
                    self.ingester(data)
                except queue.Empty:
                    continue
                except Exception:
                    continue
            return ""

    def create_session(self, ingester: callable):
        self.sender = self.Sender([], None)
        self.listener = self.Listener([], ingester, None, self.stop_event)
        threading.Thread(target=self.listener.listen, daemon=True).start()
        HTTPModule.session_ready.set()

    @classmethod
    def is_ready(cls) -> bool:
        return cls.session_ready.is_set() and not cls.stop_event.is_set()

    @classmethod
    def reset(cls):
        cls.stop_event.clear()
        cls.session_ready.clear()
        while True:
            try:
                cls.outbox_queue.get_nowait()
            except queue.Empty:
                break
        while True:
            try:
                cls.inbox_queue.get_nowait()
            except queue.Empty:
                break
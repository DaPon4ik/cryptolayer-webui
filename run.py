import sys
import os
import threading
import time
import webbrowser
import logging
from logging.handlers import RotatingFileHandler

def get_log_path() -> str:
    if getattr(sys, "frozen", False):
        if os.name == "nt":
            base = os.environ.get("APPDATA", os.path.dirname(sys.executable))
        else:
            base = os.path.join(os.path.expanduser("~"), ".cryptolayer-gui")
        logs_dir = os.path.join(base, "CryptoLayerGUI", "logs")
    else:
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

    os.makedirs(logs_dir, exist_ok=True)
    return os.path.join(logs_dir, "cryptolayer.log")

_log_handler = RotatingFileHandler(get_log_path(), maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])

if getattr(sys, "frozen", False):
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont

import uvicorn
from main import app

URL = "http://127.0.0.1:8000"

server_instance = None
shutting_down = False

def run_server():
    global server_instance
    config = uvicorn.Config(app, host="127.0.0.1", port=8000,log_level="info",access_log=False)
    server_instance = uvicorn.Server(config)
    server_instance.run()

def open_browser():
    webbrowser.open(URL)

def find_icon_path():
    base = sys._MEIPASS if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(base, "static", "images", "logo.ico"), os.path.join(base, "stuff", "logo.ico")):
        if os.path.exists(candidate):
            return candidate
    return None

def place_bottom_right(window, margin=30):
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    window.adjustSize()
    x = area.right() - window.width() - margin + 1
    y = area.bottom() - window.height() - margin + 1
    window.move(x, y-25)

class ControlWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CryptoLayer")
        self.setFixedSize(300, 160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("CryptoLayer запущен")
        font = QFont("Segoe UI", 11)
        font.setWeight(QFont.Weight.Bold)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        btn_open = QPushButton("Открыть страницу")
        btn_open.clicked.connect(open_browser)
        layout.addWidget(btn_open)

        btn_close = QPushButton("Закрыть окно и выключить сервер")
        btn_close.clicked.connect(self.shutdown)
        layout.addWidget(btn_close)

    def closeEvent(self, event):
        self.shutdown()
        event.accept()

    def shutdown(self):
        global shutting_down
        if shutting_down:
            return
        shutting_down = True
        if server_instance is not None:
            server_instance.should_exit = True
        QApplication.quit()

def main():
    threading.Thread(target=run_server, daemon=True).start()

    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(True)
    qapp.setStyleSheet("""
        QWidget {
            background-color: #141414;
            color: #e4e6eb;
        }
        QPushButton {
            background-color: #2a2a2a;
            border: 1px solid #3a3a3a;
            border-radius: 6px;
            padding: 8px;
            color: #e4e6eb;
        }
        QPushButton:hover { background-color: #383838; }
        QPushButton:pressed { background-color: #244A79; }
    """)

    icon_path = find_icon_path()
    if icon_path:
        qapp.setWindowIcon(QIcon(icon_path))

    window = ControlWindow()
    place_bottom_right(window)
    window.show()

    QTimer.singleShot(1500, open_browser)

    qapp.exec()

    time.sleep(1)
    os._exit(0)

if __name__ == "__main__":
    main()
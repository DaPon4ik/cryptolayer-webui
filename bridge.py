import time
import requests

A = "http://127.0.0.1:8000"
B = "http://127.0.0.1:8001"


def move(src, dst):
    try:
        r = requests.get(f"{src}/http-module/outbox", timeout=5)
        items = r.json().get("items", [])
        for item in items:
            data = item["data"]

            # Логирование передаваемого сообщения
            print(f"{src} -> {dst}")
            print(f"  пэйлод: {data}")

            requests.post(
                f"{dst}/http-module/inbox",
                json={"data": data},
                timeout=5,
            )
    except Exception as e:
        print(f"о {src} -> {dst}: {e}")


while True:
    move(A, B)
    move(B, A)
    time.sleep(0.1)
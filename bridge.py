import time
import requests

A = "http://127.0.0.1:8000"
B = "http://127.0.0.1:8001"


def move(src, dst):
    try:
        r = requests.get(f"{src}/http-module/outbox", timeout=5)
        items = r.json().get("items", [])
        for item in items:
            requests.post(
                f"{dst}/http-module/inbox",
                json={"data": item["data"]},
                timeout=5,
            )
    except Exception as e:
        print("bridge error:", e)


while True:
    move(A, B)
    move(B, A)
    time.sleep(0.1)
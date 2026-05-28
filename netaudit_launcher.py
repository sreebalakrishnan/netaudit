import socket
import threading
import time
import webbrowser

import uvicorn

from config import API_HOST, API_PORT


def find_free_port(host: str, preferred: int, attempts: int = 10) -> int:
    for offset in range(attempts):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in {preferred}..{preferred + attempts - 1}")


def open_browser_when_ready(url: str):
    time.sleep(1.0)
    webbrowser.open(url)


def main():
    port = find_free_port(API_HOST, API_PORT)
    url = f"http://{API_HOST}:{port}"
    print(f"NetAudit starting at {url}")
    threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()
    from api import app
    uvicorn.run(app, host=API_HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()

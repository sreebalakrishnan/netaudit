import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

import db
import scanner
from config import SCAN_SUBNET


def get_template_dir() -> Path:
    """Resolve templates dir in dev mode AND inside a py2app bundle."""
    candidates = [
        Path(__file__).resolve().parent / "templates",
        Path.cwd() / "templates",
    ]
    # py2app: Resources/ sits next to Resources/lib/python.../site-packages
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.executable).resolve().parent.parent / "Resources" / "templates")
    for c in candidates:
        if (c / "index.html").exists():
            return c
    raise RuntimeError(f"templates/index.html not found in: {candidates}")


templates = Jinja2Templates(directory=str(get_template_dir()))

app = FastAPI(title="NetAudit", version="0.1.0")
db.init()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/scan")
def start_scan():
    scan_id = db.create_scan(SCAN_SUBNET)

    def run():
        try:
            resolved, devices = scanner.scan(SCAN_SUBNET)
            db.insert_devices(scan_id, devices)
            db.finish_scan(scan_id, len(devices), status="done")
        except Exception as e:
            db.finish_scan(scan_id, 0, status=f"error: {e}")

    threading.Thread(target=run, daemon=True).start()
    return {"scan_id": scan_id}


@app.get("/api/scan/{scan_id}")
def get_scan(scan_id: int):
    s = db.get_scan(scan_id)
    if not s:
        raise HTTPException(404, "scan not found")
    s["devices"] = db.get_devices(scan_id)
    return s


@app.get("/api/scans")
def list_scans():
    return db.list_scans()

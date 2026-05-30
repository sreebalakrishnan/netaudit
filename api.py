import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

import db
import network
import scanner
import settings as user_settings
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
    subnet = user_settings.load().get("scan_subnet", SCAN_SUBNET)
    scan_id = db.create_scan(subnet)

    def run():
        try:
            resolved, devices = scanner.scan(subnet)
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


@app.get("/api/network/check")
def network_check():
    s = user_settings.load()
    return network.run_all(speed_test_enabled=s["speed_test_enabled"])


@app.get("/api/settings")
def get_settings():
    return user_settings.load()


@app.put("/api/settings")
async def put_settings(request: Request):
    body = await request.json()
    return user_settings.update(body)


@app.post("/api/quit")
def quit_app():
    """Trigger a clean macOS app termination from the UI Exit button."""
    import threading
    import time

    def _quit():
        time.sleep(0.15)  # let the HTTP response flush
        try:
            from PyObjCTools.AppHelper import callAfter
            from AppKit import NSApp
            callAfter(lambda: NSApp.terminate_(None))
        except Exception:
            # Dev mode (no AppKit) — fall back to signaling self
            import os, signal
            os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_quit, daemon=True).start()
    return {"status": "quitting"}


@app.post("/api/report")
def save_report():
    """Snapshot: latest safety check + latest finished scan, saved as JSON.

    Useful for café A/B comparison — run audits at different networks and
    diff the reports later.
    """
    from datetime import datetime, timezone
    import json as _json
    import re as _re
    from pathlib import Path

    safety = network.run_all()
    scans = db.list_scans(limit=1)
    last_scan = None
    if scans:
        last_scan = db.get_scan(scans[0]["id"])
        if last_scan:
            last_scan["devices"] = db.get_devices(scans[0]["id"])

    ssid = (safety.get("wifi") or {}).get("ssid") or "unknown"
    slug = _re.sub(r"[^A-Za-z0-9-]", "_", ssid)[:24] or "unknown"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    reports_dir = Path(user_settings.load()["reports_dir"]).expanduser()
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{ts}_{slug}.json"
    path.write_text(_json.dumps({
        "timestamp_utc": ts,
        "ssid": ssid,
        "safety": safety,
        "scan": last_scan,
    }, indent=2, default=str))
    return {"path": str(path)}

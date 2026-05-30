"""User-editable settings, persisted to ~/.netaudit/config.json.

Read on startup + on every API call (cheap). Writes go through update()
which atomically rewrites the file. Defaults are merged with whatever
is on disk so adding a new setting doesn't break existing configs.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from config import DATA_DIR

SETTINGS_PATH = DATA_DIR / "config.json"
_lock = Lock()

DEFAULTS: dict = {
    "theme": "dark",                 # "light" | "dark" | "system"
    "scan_subnet": "auto",           # "auto" | "<cidr>"
    "safety_poll_minutes": 2,        # menu-bar verdict refresh cadence
    "speed_test_enabled": True,      # turn off on metered / slow connections
    "reports_dir": str(DATA_DIR / "reports"),
}


def _read_disk() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except Exception:
        return {}


def load() -> dict:
    """Return defaults merged with whatever's on disk."""
    return {**DEFAULTS, **_read_disk()}


def update(patch: dict) -> dict:
    """Write a partial update; return the full merged settings."""
    with _lock:
        current = load()
        current.update(patch)
        # Validate before persisting
        current = _validate(current)
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(current, indent=2))
    return current


def _validate(s: dict) -> dict:
    if s.get("theme") not in ("light", "dark", "system"):
        s["theme"] = "dark"
    try:
        s["safety_poll_minutes"] = max(1, min(60, int(s["safety_poll_minutes"])))
    except Exception:
        s["safety_poll_minutes"] = 2
    s["speed_test_enabled"] = bool(s.get("speed_test_enabled", True))
    sub = s.get("scan_subnet") or "auto"
    s["scan_subnet"] = sub if sub == "auto" else str(sub)
    rd = s.get("reports_dir") or DEFAULTS["reports_dir"]
    s["reports_dir"] = str(Path(rd).expanduser())
    return s

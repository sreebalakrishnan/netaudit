import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    subnet TEXT NOT NULL,
    status TEXT NOT NULL,
    device_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    ip TEXT NOT NULL,
    mac TEXT,
    hostname TEXT,
    vendor TEXT,
    device_type TEXT,
    brand TEXT,
    model TEXT,
    confidence TEXT,
    services TEXT,
    open_ports TEXT,
    ssdp TEXT,
    UNIQUE(scan_id, ip)
);

CREATE INDEX IF NOT EXISTS idx_devices_scan ON devices(scan_id);
CREATE INDEX IF NOT EXISTS idx_scans_started ON scans(started_at DESC);
"""

# Columns added after v0.1 — idempotent ALTERs
_NEW_COLUMNS = [
    ("device_type", "TEXT"),
    ("brand", "TEXT"),
    ("model", "TEXT"),
    ("confidence", "TEXT"),
    ("services", "TEXT"),
    ("open_ports", "TEXT"),
    ("ssdp", "TEXT"),
]


def init():
    with connect() as con:
        con.executescript(SCHEMA)
        existing = {r["name"] for r in con.execute("PRAGMA table_info(devices)").fetchall()}
        for col, typ in _NEW_COLUMNS:
            if col not in existing:
                con.execute(f"ALTER TABLE devices ADD COLUMN {col} {typ}")


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
    finally:
        con.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_scan(subnet: str) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO scans (started_at, subnet, status) VALUES (?, ?, 'running')",
            (_now(), subnet),
        )
        return cur.lastrowid


def finish_scan(scan_id: int, device_count: int, status: str = "done"):
    with connect() as con:
        con.execute(
            "UPDATE scans SET finished_at = ?, status = ?, device_count = ? WHERE id = ?",
            (_now(), status, device_count, scan_id),
        )


def insert_devices(scan_id: int, devices: list[dict]):
    if not devices:
        return
    with connect() as con:
        con.executemany(
            """INSERT OR REPLACE INTO devices
               (scan_id, ip, mac, hostname, vendor, device_type, brand, model,
                confidence, services, open_ports, ssdp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    scan_id,
                    d.get("ip"), d.get("mac"), d.get("hostname"), d.get("vendor"),
                    d.get("device_type"), d.get("brand"), d.get("model"),
                    d.get("confidence"),
                    json.dumps(d.get("services") or []),
                    json.dumps(d.get("open_ports") or []),
                    json.dumps(d.get("ssdp") or []),
                )
                for d in devices
            ],
        )


def get_scan(scan_id: int) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        return dict(row) if row else None


def list_scans(limit: int = 20) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM scans ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_devices(scan_id: int) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            """SELECT ip, mac, hostname, vendor, device_type, brand, model,
                      confidence, services, open_ports, ssdp
               FROM devices WHERE scan_id = ? ORDER BY ip""",
            (scan_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("services", "open_ports", "ssdp"):
                try: d[k] = json.loads(d[k]) if d[k] else []
                except Exception: d[k] = []
            out.append(d)
        return out

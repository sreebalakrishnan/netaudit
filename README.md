# NetAudit

A native macOS app for auditing your LAN — discovers devices on your subnet, surfaces them through a local web UI, persists scans to SQLite.

Live: [netaudit.sreeb.dev](https://netaudit.sreeb.dev)

## Status

v0.1 MVP — working. Bundled `NetAudit.app` (~70 MB) launches, auto-opens browser, discovers devices via ping sweep + `arp -a` (rootless — no sudo prompts).

## Run from source

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv venv_build
source venv_build/bin/activate
pip install -r requirements.txt
python netaudit_launcher.py
```

Opens at `http://127.0.0.1:8000` (or next free port).

## Build the .app

```bash
source venv_build/bin/activate
python setup.py py2app
open dist/NetAudit.app
# Deploy:
cp -r dist/NetAudit.app /Applications/
```

## Layout

```
api.py                 FastAPI routes (/, /api/scan, /api/scans)
scanner.py             ping sweep + arp -a parsing, vendor lookup
db.py                  SQLite at ~/.netaudit/network_audit.db
config.py              env vars (API_HOST, API_PORT, SCAN_SUBNET)
netaudit_launcher.py   Entry point for .app, picks free port, opens browser
setup.py               py2app config
templates/index.html   web UI (dark, vanilla JS)
```

## Notes / MVP scope

- **Rootless scan** — uses subprocess `ping` + `arp -a`, not `scapy` raw sockets. Trades depth for "double-click and it works" UX (no sudo prompt). Docs in `docs/` mention scapy/paramiko as future direction.
- **MAC randomization** — most modern phones/laptops use randomized MACs on Wi-Fi, so vendor lookup will be null for them. Expected.
- **Python 3.12** — py2app 0.28.x doesn't support 3.13+. Install via `brew install python@3.12`.

## Docs

- [`docs/MAC_APP_README.txt`](docs/MAC_APP_README.txt) — overview
- [`docs/MAC_APP_COMPLETE_GUIDE.md`](docs/MAC_APP_COMPLETE_GUIDE.md) — full reference
- [`docs/BUILD_MAC_APP.md`](docs/BUILD_MAC_APP.md) — step-by-step py2app guide

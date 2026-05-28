# NetAudit

A native macOS app for auditing your home/office network — discovers devices, profiles them, and surfaces findings through a local web UI.

Live: [netaudit.sreeb.dev](https://netaudit.sreeb.dev)

## Status

Early scaffolding. Currently capturing the build plan; source code lands next.

## Docs

See [`docs/`](docs/):

- [`MAC_APP_README.txt`](docs/MAC_APP_README.txt) — overview & quick start
- [`MAC_APP_COMPLETE_GUIDE.md`](docs/MAC_APP_COMPLETE_GUIDE.md) — full reference
- [`BUILD_MAC_APP.md`](docs/BUILD_MAC_APP.md) — step-by-step py2app build

## Quick build (once source lands)

```bash
python3 -m venv venv_build
source venv_build/bin/activate
pip install -r requirements.txt
python setup.py py2app
open dist/NetAudit.app
```

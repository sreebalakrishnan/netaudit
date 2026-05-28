# 🍎 NetAudit as Standalone Mac Application

## What's New

You now have **everything you need to build a professional Mac app** with Python and all dependencies embedded. Zero external dependencies needed by end users.

### Files Added

```
netaudit/
├── netaudit_launcher.py       ← NEW: Entry point for Mac app
├── setup.py                   ← NEW: py2app build configuration
├── BUILD_MAC_APP.md           ← NEW: Complete py2app guide
├── BUILD_MAC_APP_PYINSTALLER.md ← NEW: PyInstaller alternative
├── MAC_APP_QUICK_START.md     ← NEW: Quick reference
├── requirements.txt           ← UPDATED: Added py2app
└── api.py                     ← UPDATED: Compatible with bundled paths
```

---

## How It Works

### Traditional Way (Requires End User to Have Python)
```
User's Mac
  └─ Open Terminal
  └─ pip install requirements
  └─ python api.py
  └─ Open http://localhost:8000
```
**Problem:** Requires Python, venv, pip knowledge. 😞

### New Way (Standalone Mac App)
```
User's Mac
  └─ Double-click NetAudit.app
  └─ Auto-opens http://localhost:8000
  └─ Use the app
```
**Benefit:** Looks and feels like native app. Zero setup. ✨

---

## Build Process Overview

### Option 1: py2app (Recommended) ✅

**Most native Mac experience**

```bash
cd /home/claude/netaudit

# Create build environment
python3 -m venv venv_build
source venv_build/bin/activate

# Install dependencies (including py2app)
pip install -r requirements.txt

# Build the .app
python setup.py py2app
```

**Result:** `dist/NetAudit.app` (self-contained, ~150 MB)

**Time:** 3-5 minutes

**Read:** `BUILD_MAC_APP.md` for complete guide

---

### Option 2: PyInstaller (Faster, Simpler)

**Quicker alternative, slightly less native**

```bash
cd /home/claude/netaudit

python3 -m venv venv_pyinstaller
source venv_pyinstaller/bin/activate

pip install -r requirements.txt
pip install pyinstaller

pyinstaller --onedir --windowed --name=NetAudit --add-data="templates:templates" netaudit_launcher.py
```

**Result:** `dist/NetAudit/` → requires manual .app structure

**Time:** 2-3 minutes

**Read:** `BUILD_MAC_APP_PYINSTALLER.md` for complete guide

---

## Quick Decision

**Use py2app if:**
- ✅ You want maximum native macOS integration
- ✅ You plan to share with others eventually
- ✅ You want easiest maintenance

**Use PyInstaller if:**
- ✅ You want fastest build
- ✅ You prefer simpler configuration
- ✅ You're OK with 30 MB larger app

**Recommendation:** Start with **py2app** (recommended for macOS).

---

## Your Build Path (py2app)

### 1. Prepare
```bash
cd /home/claude/netaudit

python3 -m venv venv_build
source venv_build/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

This installs:
- **Runtime:** scapy, paramiko, fastapi, uvicorn, pydantic, jinja2
- **Build:** py2app, setuptools, wheel

### 3. Build
```bash
python setup.py py2app
```

**Expected output:**
```
running py2app
creating build/bdist.macosx-...
...
Completed!
```

### 4. Test
```bash
open dist/NetAudit.app
```

Should auto-launch with:
1. Terminal window (showing logs)
2. Browser opening to http://localhost:8000
3. NetAudit UI loads and works normally

### 5. Deploy
```bash
cp -r dist/NetAudit.app /Applications/
```

Now you can:
- Double-click from Finder → Applications
- Drag to Dock for quick access
- Share the .app file with others

---

## What's Embedded in the .app

```
NetAudit.app/Contents/
├── MacOS/
│   └── NetAudit           ← Executable launcher
├── Resources/
│   ├── templates/
│   │   └── index.html     ← Web UI
│   ├── lib/python3.X/     ← Python interpreter + all packages
│   │   ├── scapy/
│   │   ├── paramiko/
│   │   ├── fastapi/
│   │   ├── uvicorn/
│   │   └── ... (all deps)
│   └── __pycache__/
└── Info.plist             ← App metadata
```

**Total size:** ~150 MB (typical for bundled Python apps)

---

## User Experience After Build

### First Time
```
1. User double-clicks NetAudit.app
2. Terminal window appears (showing logs)
3. Browser auto-opens to http://localhost:8000
4. NetAudit UI loads
5. User clicks "▶ Start Scan"
6. Everything works as normal
```

### To Stop App
- Close the terminal window, or
- Press Ctrl+C in terminal, or
- Cmd+Alt+Esc → Force Quit

---

## Key Features of Bundled App

✅ **Self-contained** — No external Python needed  
✅ **All dependencies embedded** — scapy, paramiko, fastapi, etc. all built-in  
✅ **Double-click launch** — Looks and feels native  
✅ **Auto-opens browser** — User doesn't need to type URLs  
✅ **Persistent database** — Stored in ~/.netaudit/ (survives app updates)  
✅ **Easy to share** — Just copy the .app file  

---

## Build Configuration Explained

### In `setup.py`

```python
APP = ["netaudit_launcher.py"]  # Entry point

DATA_FILES = [
    ("templates", ["templates/index.html"])  # Include UI
]

OPTIONS = {
    "py2app": {
        "packages": [...],    # Include all packages
        "includes": [...],    # Include all modules
        "strip": True,        # Reduce size
        "arch": "arm64",      # M1/M2 Macs (use "x86_64" for Intel)
    }
}
```

### In `netaudit_launcher.py`

```python
def main():
    # Import FastAPI app
    from api import app
    import uvicorn
    
    # Auto-open browser
    webbrowser.open("http://127.0.0.1:8000")
    
    # Start server (blocking)
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

### In `api.py`

Added path resolution for bundled .app:
```python
def get_template_path():
    """Works in dev mode AND bundled .app"""
    # Try current dir, then relative path, then bundled path
    # Returns correct templates/index.html regardless of context
```

---

## Advanced Options

### Custom Icon

```bash
# Convert PNG to macOS icon format
convert icon.png -define icon:auto-resize icon.icns

# In setup.py:
"iconfile": "icon.icns"

# Rebuild
```

### Code Signing (For Distribution)

```bash
# Sign the app
codesign --deep --force --verify --sign "Apple Development" dist/NetAudit.app

# Notarize (requires Apple Developer account)
xcrun notarytool submit dist/NetAudit.dmg --apple-id your-email@apple.com
```

### Create Disk Image (DMG)

```bash
hdiutil create -volname "NetAudit" -srcfolder dist/NetAudit.app -format UDZO NetAudit.dmg
```

These are **optional** for personal use. Required only for public distribution.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "py2app not found" | `pip install py2app` in active venv |
| Build fails | Run from project root: `cd /home/claude/netaudit` |
| App won't launch | Check error: `open -a NetAudit --args` |
| Port 8000 in use | Edit `.env`: `API_PORT=8001` |
| Database missing | Create dir: `mkdir -p ~/.netaudit` |
| Templates not found | Verify: `ls templates/index.html` exists |

---

## File Reference

| File | Purpose |
|------|---------|
| `netaudit_launcher.py` | Entry point, auto-opens browser, starts server |
| `setup.py` | py2app configuration, defines what to bundle |
| `api.py` | Updated with `get_template_path()` for bundled paths |
| `BUILD_MAC_APP.md` | Complete detailed guide with all options |
| `BUILD_MAC_APP_PYINSTALLER.md` | Alternative using PyInstaller |
| `MAC_APP_QUICK_START.md` | Quick reference card |

---

## Architecture Diagram

```
Development Mode
├─ python api.py
└─ Terminal → Browser → http://localhost:8000

Bundled .app Mode
├─ Double-click NetAudit.app
├─ macOS launches netaudit_launcher.py
├─ Launcher imports api.py, etc.
├─ Launcher calls webbrowser.open()
├─ FastAPI server starts
└─ Browser auto-opens → http://localhost:8000
```

---

## Deployment Scenarios

### Scenario 1: Personal Use
```
1. Build on your Mac
2. Test the app
3. Move to /Applications/
4. Done!
```

### Scenario 2: Share with Sripriya
```
1. Build on your Mac
2. Test on another Mac (or use simulator)
3. Email the .app file to Sripriya
4. She double-clicks, works instantly
```

### Scenario 3: Share on Website
```
1. Build + test on your Mac
2. Code sign + notarize (Apple Developer account needed)
3. Create DMG (disk image)
4. Host on website for download
5. Users download, install, enjoy
```

For scenarios 1-2, **no code signing needed**. For scenario 3, **code signing is required by Apple for gatekeeper**.

---

## What's Changed from Original MVP

| Aspect | Original | With Mac App |
|--------|----------|-------------|
| **Install** | `pip install -r requirements.txt` | Double-click .app |
| **Dependencies** | External (user must install) | Bundled in .app |
| **Python** | System Python (user must have) | Embedded |
| **Distribution** | Code + setup docs | Single .app file |
| **User Experience** | Technical (terminal, python, venv) | Native (double-click) |

---

## Next Steps

### Immediate (Today)
1. Read `BUILD_MAC_APP.md` (5 min)
2. Run the build (5 min)
3. Test `dist/NetAudit.app` (5 min)

### This Week
1. Deploy to `/Applications/`
2. Use it as your daily network audit tool
3. Verify it works with your network

### Future
1. Add custom icon (optional)
2. Create DMG for easier sharing (optional)
3. Code sign + notarize if sharing widely (optional)

---

## Success Checklist

After building:

- [ ] Build completes without errors
- [ ] `dist/NetAudit.app` exists and is ~150 MB
- [ ] `open dist/NetAudit.app` launches the app
- [ ] Terminal window appears with logs
- [ ] Browser auto-opens to http://localhost:8000
- [ ] NetAudit UI loads and displays
- [ ] "▶ Start Scan" works
- [ ] Scan discovers devices
- [ ] Database created at ~/.netaudit/network_audit.db
- [ ] App works identically to dev version

---

## Quick Command Reference

```bash
# Full build process
cd /home/claude/netaudit
python3 -m venv venv_build
source venv_build/bin/activate
pip install -r requirements.txt
python setup.py py2app

# Test
open dist/NetAudit.app

# Deploy
cp -r dist/NetAudit.app /Applications/

# Clean for next build
rm -rf build dist
```

---

## Summary

You now have a **production-ready process** to turn NetAudit into a **native Mac application** that:

- ✅ Looks and feels like a native Mac app
- ✅ Contains all Python + dependencies (no external deps)
- ✅ Launches with double-click
- ✅ Auto-opens web UI
- ✅ Is easy to share
- ✅ Can be distributed to App Store (with notarization)

**Start with py2app. Build takes 5 minutes. Result is a professional Mac app.** 🚀

---

**Ready?** Read `BUILD_MAC_APP.md` and start building!

Questions? Check the troubleshooting section or explore the source code — it's all well-commented.

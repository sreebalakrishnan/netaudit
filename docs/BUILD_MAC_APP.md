# 🍎 Building NetAudit as a Mac App

Complete guide to package NetAudit as a standalone **NetAudit.app** that you can double-click to run.

## Overview

This creates a **native macOS application bundle** with:
- ✅ Python interpreter embedded
- ✅ All dependencies bundled (scapy, paramiko, fastapi, etc.)
- ✅ No need to install Python, pip, or anything
- ✅ Double-click to run
- ✅ Auto-opens browser to http://localhost:8000
- ✅ Completely self-contained

Output: **`dist/NetAudit.app`** (~150-200 MB)

---

## Prerequisites

- macOS 11+ (Intel or Apple Silicon)
- Python 3.9+ installed (for building only)
- Xcode Command Line Tools: `xcode-select --install`

---

## Build Steps

### Step 1: Prepare Environment

```bash
cd /home/claude/netaudit

# Create fresh virtual environment
python3 -m venv venv_build
source venv_build/bin/activate
```

### Step 2: Install Build Dependencies

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

This installs:
- All runtime dependencies (scapy, paramiko, fastapi, etc.)
- **py2app** (creates .app bundles)

### Step 3: Build the App

```bash
python setup.py py2app
```

**This will take 2-5 minutes.** You'll see:
```
running py2app
creating build/bdist.macosx-...
...
Completed!
```

### Step 4: Verify Build

The output .app bundle is at:
```bash
ls -la dist/NetAudit.app
```

You should see:
```
dist/NetAudit.app/
├── Contents/
│   ├── MacOS/
│   │   └── NetAudit          ← Main executable
│   ├── Resources/
│   │   ├── templates/
│   │   │   └── index.html    ← Web UI
│   │   ├── __pycache__/
│   │   └── lib/              ← All Python + dependencies
│   └── Info.plist             ← App metadata
```

### Step 5: Test the App

Double-click to launch:
```bash
open dist/NetAudit.app
```

Or from terminal:
```bash
open -a "NetAudit"
```

**Expected behavior:**
1. App window opens (shows logs)
2. Browser automatically opens to http://localhost:8000
3. NetAudit UI loads
4. Click "▶ Start Scan"

**To stop:** Close the terminal window, or press Ctrl+C

---

## Deployment

### For Personal Use

You're done! Just:
1. Move `dist/NetAudit.app` to `/Applications/`
2. Double-click whenever you want to run a scan

```bash
cp -r dist/NetAudit.app /Applications/
# Now in Finder: Applications → NetAudit.app → Open
```

### For Distribution (Optional)

If you want to share with others, you need **code signing** and **notarization**:

#### A. Get Developer Certificate

```bash
# Apple Developer account required
# In Xcode: Preferences → Accounts → Download Manual Profiles
```

#### B. Update setup.py

```python
# In setup.py, uncomment:
"codesign_identity": "Apple Development",
```

#### C. Sign the App

```bash
codesign --deep --force --verify --verbose --sign "Apple Development" dist/NetAudit.app
```

#### D. Create DMG (Optional)

```bash
# Create a disk image for distribution
hdiutil create -volname "NetAudit" -srcfolder dist/NetAudit.app -ov -format UDZO NetAudit.dmg
```

#### E. Notarize (Apple requirement for distribution)

```bash
# This requires Apple Developer account
xcrun notarytool submit NetAudit.dmg --apple-id your-email@apple.com
```

**For personal use, steps A-E are NOT required.** Distribution is optional.

---

## App Architecture

### How It Works

```
NetAudit.app
├── User double-clicks
├── macOS launches netaudit_launcher.py
├── Launcher imports api.py, config.py, scanner.py, db.py
├── FastAPI server starts on http://127.0.0.1:8000
├── Launcher auto-opens browser
└── User interacts with web UI
```

### File Locations in .app Bundle

```
dist/NetAudit.app/Contents/
├── MacOS/
│   └── NetAudit              ← py2app launcher wrapper
├── Resources/
│   ├── __pycache__/          ← Compiled Python modules
│   ├── lib/python3.X/        ← All dependencies
│   │   └── site-packages/    ← scapy, paramiko, fastapi, etc.
│   └── templates/
│       └── index.html        ← Web UI
└── Info.plist                ← App metadata (name, version, etc.)
```

### Database Location

Still stored at:
```
~/.netaudit/network_audit.db
```

This is **outside** the .app bundle, so it persists across updates.

---

## Troubleshooting

### "py2app not found"

```bash
# Make sure build venv is activated
source venv_build/bin/activate
pip install py2app
python setup.py py2app
```

### "No such file or directory: templates/index.html"

The build must be run from project root:
```bash
cd /home/claude/netaudit
python setup.py py2app
```

### App crashes immediately

Check the error:
```bash
# Run from terminal to see error output
open -a NetAudit --args
```

Or check system logs:
```bash
log stream --predicate 'process == "NetAudit"' --level debug
```

### Port 8000 already in use

Edit `.env`:
```
API_PORT=8001
```

Then rebuild.

### Browser doesn't auto-open

The server is running fine; just manually open http://localhost:8000 in your browser.

---

## App Size

| Component | Size |
|-----------|------|
| Python interpreter | ~40 MB |
| Dependencies (scapy, paramiko, etc.) | ~60 MB |
| FastAPI + uvicorn | ~30 MB |
| NetAudit code | ~100 KB |
| **Total** | **~130-150 MB** |

This is typical for Python bundled apps. You can reduce size slightly by:
- Using `--strip` in setup.py (already enabled)
- Using UPX compression (advanced)

---

## Updates & Versioning

To update the app:

1. Update code in project
2. Update version in `setup.py`:
   ```python
   version="0.2.0",
   OPTIONS["py2app"]["plist"]["CFBundleVersion"] = "0.2.0"
   ```
3. Rebuild:
   ```bash
   rm -rf build dist
   python setup.py py2app
   ```
4. Test the new `dist/NetAudit.app`
5. Copy to `/Applications/` (or share)

---

## macOS Compatibility

- **M1/M2 (Apple Silicon)**: Uses `arch: arm64` in setup.py ✅
- **Intel Macs**: Change to `arch: x86_64` in setup.py

To build for **both architectures** (universal binary):
```python
# In setup.py
"arch": "universal2",  # Intel + Apple Silicon
```

---

## Advanced: Custom Icon

To add a custom app icon:

### 1. Create Icon

Get a 512x512 PNG image (or download one).

### 2. Convert to .icns Format

```bash
# Requires ImageMagick
brew install imagemagick
convert icon.png -define icon:auto-resize=256,128,96,64,48,32,16 icon.icns
```

Or use online converter: https://convertio.co/png-icns/

### 3. Update setup.py

```python
OPTIONS = {
    "py2app": {
        "iconfile": "icon.icns",  # Point to your .icns file
        # ... rest of config
    }
}
```

### 4. Rebuild

```bash
rm -rf build dist
python setup.py py2app
```

---

## Stopping the App

The app runs a terminal window showing logs. To stop:

**Option 1:** Close the terminal window  
**Option 2:** Press Ctrl+C in the terminal  
**Option 3:** Force quit: Cmd+Opt+Esc → Select NetAudit → Force Quit

---

## Automating Builds

Save this as `build.sh`:

```bash
#!/bin/bash
set -e

cd /home/claude/netaudit

echo "🏗️  Building NetAudit.app..."

# Clean
rm -rf build dist venv_build

# Setup
python3 -m venv venv_build
source venv_build/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Build
python setup.py py2app

echo "✅ Build complete!"
echo "📂 Output: dist/NetAudit.app"
echo ""
echo "To test:"
echo "  open dist/NetAudit.app"
echo ""
echo "To deploy:"
echo "  cp -r dist/NetAudit.app /Applications/"
```

Make executable:
```bash
chmod +x build.sh
./build.sh
```

---

## Next: Distribution (Optional)

If you want to share NetAudit with others (Sripriya, etc.):

1. **Notarize** the app (Apple security requirement)
2. **Create DMG** (disk image) for distribution
3. **Host** for download

This requires an Apple Developer account. For now, personal use is fine without it.

---

## Key Files

| File | Purpose |
|------|---------|
| `setup.py` | py2app configuration |
| `netaudit_launcher.py` | Entry point for .app |
| `api.py` | Updated to handle bundled paths |
| `requirements.txt` | Includes py2app |

---

## Reference: Full Build Checklist

- [ ] Python 3.9+ installed
- [ ] In project root: `/home/claude/netaudit/`
- [ ] Create venv: `python3 -m venv venv_build`
- [ ] Activate: `source venv_build/bin/activate`
- [ ] Install: `pip install -r requirements.txt`
- [ ] Build: `python setup.py py2app`
- [ ] Test: `open dist/NetAudit.app`
- [ ] Deploy: `cp -r dist/NetAudit.app /Applications/`

---

**Ready to build?**

```bash
cd /home/claude/netaudit
source venv_build/bin/activate
python setup.py py2app
```

In 2-5 minutes, you'll have a fully self-contained Mac app! 🚀

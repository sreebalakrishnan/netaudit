# Code signing & notarization

Personal use does **not** need any of this — the app runs fine unsigned. You only need to sign + notarize if you want to:

- Share the `.app` or `.dmg` with someone who'll get Gatekeeper warnings otherwise
- Distribute on a website (`netaudit.sreeb.dev` download link)
- Submit to the Mac App Store

You need an **Apple Developer account** ($99/year) and a "Developer ID Application" certificate installed in your Keychain.

## 1. Build

```bash
source venv_build/bin/activate
rm -rf build dist
python setup.py py2app
```

## 2. Sign

```bash
# List your installed identities to find the right one
security find-identity -v -p codesigning

# Sign the bundle (deep = include nested frameworks)
codesign --deep --force --options runtime \
    --sign "Developer ID Application: Your Name (TEAMID)" \
    --entitlements entitlements.plist \
    dist/NetAudit.app

# Verify
codesign --verify --deep --strict --verbose=2 dist/NetAudit.app
spctl -a -t exec -vv dist/NetAudit.app
```

`entitlements.plist` should be minimal — NetAudit only needs outbound network and the ability to spawn subprocesses (`ping`, `arp`, `traceroute`, `system_profiler`, `scutil`, `route`). With the hardened runtime, you'll likely want:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.network.client</key><true/>
    <key>com.apple.security.network.server</key><true/>
</dict>
</plist>
```

## 3. Build a DMG

```bash
./build_dmg.sh
# Produces NetAudit-<version>.dmg
```

## 4. Notarize

```bash
# First time: store credentials in keychain (one-time)
xcrun notarytool store-credentials NETAUDIT_NOTARY \
    --apple-id "you@example.com" \
    --team-id "TEAMID" \
    --password "app-specific-password-from-appleid.apple.com"

# Submit and wait
xcrun notarytool submit NetAudit-*.dmg \
    --keychain-profile NETAUDIT_NOTARY \
    --wait

# Staple the ticket so it works offline
xcrun stapler staple NetAudit-*.dmg
```

## 5. Verify the notarized DMG opens cleanly on a fresh Mac

```bash
spctl -a -t open --context context:primary-signature -vv NetAudit-*.dmg
```

That's it. Drop the DMG on `netaudit.sreeb.dev` and ship.

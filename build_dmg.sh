#!/usr/bin/env bash
# Build a drag-to-Applications DMG installer from dist/NetAudit.app
#
# Output: NetAudit-<version>.dmg in the repo root.
# Assumes dist/NetAudit.app already exists (run `python setup.py py2app` first).
set -euo pipefail

APP="dist/NetAudit.app"
[[ -d "$APP" ]] || { echo "❌ $APP not found — build the app first."; exit 1; }

VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "$APP/Contents/Info.plist" 2>/dev/null || echo "dev")
DMG="NetAudit-${VERSION}.dmg"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

echo "📦 Staging $APP …"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

echo "💿 Building $DMG …"
rm -f "$DMG"
hdiutil create \
    -volname "NetAudit" \
    -srcfolder "$STAGE" \
    -ov -format UDZO \
    -fs HFS+ \
    "$DMG" >/dev/null

SIZE=$(du -h "$DMG" | cut -f1)
echo "✅ $DMG ($SIZE) — drag NetAudit.app onto the Applications shortcut to install."

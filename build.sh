#!/usr/bin/env bash
# Build NetAudit end-to-end: py2app bundle → ad-hoc sign → DMG.
#
# Output: dist/NetAudit.app, NetAudit-<version>.dmg
# Prints SHA256 of the DMG for use in the Homebrew cask formula.
#
# Usage:
#   ./build.sh                  # full build
#   ./build.sh --no-dmg         # bundle + sign only, skip DMG
#   ./build.sh --no-cask        # don't auto-update the cask formula
set -euo pipefail

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m✓\033[0m %s\n" "$1"; }
info() { printf "\033[2m  %s\033[0m\n" "$1"; }

cd "$(dirname "$0")"

SKIP_DMG=0
SKIP_CASK=0
for arg in "$@"; do
    case "$arg" in
        --no-dmg)  SKIP_DMG=1 ;;
        --no-cask) SKIP_CASK=1 ;;
        *) echo "unknown arg: $arg"; exit 2 ;;
    esac
done

# 0. Activate venv if not already in one
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    [[ -d venv_build ]] || {
        echo "venv_build/ not found. Create with:"
        echo "  /opt/homebrew/opt/python@3.12/bin/python3.12 -m venv venv_build"
        echo "  source venv_build/bin/activate && pip install -r requirements.txt"
        exit 1
    }
    # shellcheck source=/dev/null
    source venv_build/bin/activate
fi

# 1. Regenerate icon (cheap; keeps it in sync with generate_icon.py)
bold "1/5 Generating icon…"
python assets/generate_icon.py >/dev/null
iconutil -c icns assets/NetAudit.iconset -o NetAudit.icns
ok "NetAudit.icns ($(du -h NetAudit.icns | cut -f1))"

# 2. Clean previous build
bold "2/5 Cleaning previous build…"
rm -rf build dist NetAudit-*.dmg
ok "Cleaned build/, dist/, *.dmg"

# 3. Build the bundle with py2app
bold "3/5 Building bundle with py2app…"
python setup.py py2app 2>&1 | tail -1
[[ -d dist/NetAudit.app ]] || { echo "✗ py2app didn't produce dist/NetAudit.app"; exit 1; }
ok "dist/NetAudit.app ($(du -sh dist/NetAudit.app | cut -f1))"

# 4. Deep ad-hoc sign
bold "4/5 Deep ad-hoc signing…"
codesign --force --deep --sign - dist/NetAudit.app 2>&1 | sed -n '1p'
codesign --verify --deep --strict dist/NetAudit.app 2>&1 | tail -1 || true
ok "Signed (ad-hoc — Gatekeeper will still warn until notarized)"

# 5. DMG + checksum
VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" dist/NetAudit.app/Contents/Info.plist)
DMG="NetAudit-${VERSION}.dmg"

if (( SKIP_DMG )); then
    info "Skipping DMG (--no-dmg)"
else
    bold "5/5 Packaging DMG…"
    ./build_dmg.sh
    SHA=$(shasum -a 256 "$DMG" | cut -d' ' -f1)
    ok "$DMG ($(du -h "$DMG" | cut -f1))"
    info "sha256: $SHA"

    # Auto-update the cask formula so brew users get the new version
    if [[ $SKIP_CASK -eq 0 && -f homebrew/Casks/netaudit.rb ]]; then
        /usr/bin/sed -i.bak \
            -E "s/version \"[^\"]*\"/version \"$VERSION\"/; s/sha256 \"[a-f0-9]+\"/sha256 \"$SHA\"/" \
            homebrew/Casks/netaudit.rb
        rm -f homebrew/Casks/netaudit.rb.bak
        ok "Updated homebrew/Casks/netaudit.rb → v$VERSION, sha256=${SHA:0:16}…"
    fi
fi

echo ""
bold "Done — NetAudit v$VERSION"
echo ""
echo "  Test:        open dist/NetAudit.app"
echo "  Install:     cp -r dist/NetAudit.app /Applications/"
if (( SKIP_DMG == 0 )); then
echo "  Share:       upload $DMG → netaudit.sreeb.dev"
echo "  Brew users:  brew install sreebalakrishnan/netaudit/netaudit"
fi

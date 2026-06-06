#!/usr/bin/env bash
# One-line installer for NetAudit.
#
# Usage:
#   curl -fsSL https://netaudit.sreeb.dev/install.sh | bash
#
# What it does:
#   1. Downloads the latest NetAudit DMG to a temp file
#   2. Mounts it
#   3. Copies NetAudit.app into /Applications (overwriting any existing copy)
#   4. Strips the macOS quarantine attribute so Gatekeeper doesn't block launch
#   5. Unmounts and cleans up
#
# No sudo required. The script will ask before overwriting if an existing
# NetAudit.app is in /Applications.
set -euo pipefail

# Where the DMG lives — the stable-named asset on the latest GitHub Release.
# Override with NETAUDIT_DMG_URL=... if you mirror it (e.g. netaudit.sreeb.dev).
DMG_URL="${NETAUDIT_DMG_URL:-https://github.com/sreebalakrishnan/netaudit/releases/latest/download/NetAudit.dmg}"

APP_NAME="NetAudit.app"
DEST="/Applications/$APP_NAME"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "\033[33m!\033[0m %s\n" "$1"; }
die()  { printf "\033[31m✗\033[0m %s\n" "$1" >&2; exit 1; }

bold "Installing NetAudit…"

# --- 0. Sanity checks ---
[[ "$(uname)" == "Darwin" ]] || die "NetAudit is a macOS app; this script only runs on macOS."

# --- 1. Confirm overwrite if app already exists ---
if [[ -d "$DEST" ]]; then
    INSTALLED_VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "$DEST/Contents/Info.plist" 2>/dev/null || echo "?")
    warn "$DEST already exists (version $INSTALLED_VERSION)."
    if [[ -t 0 ]]; then
        read -r -p "Replace it? [y/N] " ans
        [[ "$ans" =~ ^[Yy]$ ]] || die "Aborted by user."
    else
        warn "(running non-interactively — will replace)"
    fi
fi

# --- 2. Download DMG to a temp file ---
TMP=$(mktemp -d -t netaudit-install)
trap 'rm -rf "$TMP"; [[ -n "${MOUNT:-}" && -d "$MOUNT" ]] && hdiutil detach -quiet "$MOUNT" 2>/dev/null || true' EXIT
DMG="$TMP/NetAudit.dmg"

ok "Downloading $DMG_URL …"
curl -fsSL --progress-bar "$DMG_URL" -o "$DMG" || die "Download failed."

SIZE=$(du -h "$DMG" | cut -f1)
ok "Got $SIZE."

# --- 3. Mount ---
ok "Mounting disk image…"
MOUNT=$(hdiutil attach -nobrowse -readonly "$DMG" | tail -1 | awk '{print $NF}')
[[ -d "$MOUNT/$APP_NAME" ]] || die "Mounted image doesn't contain $APP_NAME."

# --- 4. Copy ---
ok "Copying $APP_NAME → /Applications…"
[[ -d "$DEST" ]] && rm -rf "$DEST"
cp -R "$MOUNT/$APP_NAME" "/Applications/"

# --- 5. Strip quarantine so first launch doesn't trigger Gatekeeper ---
ok "Removing quarantine attribute…"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

# --- 6. Symlink the `netaudit` terminal command onto PATH (best-effort) ---
# Point at the shim in Resources/, NOT the mach-o (py2app can't run via symlink).
EXEC="$DEST/Contents/Resources/netaudit"
LINK=""
for d in /opt/homebrew/bin /usr/local/bin; do
    if [[ -d "$d" && -w "$d" ]]; then
        ln -sf "$EXEC" "$d/netaudit" && LINK="$d/netaudit" && break
    fi
done
if [[ -z "$LINK" ]]; then
    mkdir -p "$HOME/.local/bin" && ln -sf "$EXEC" "$HOME/.local/bin/netaudit" && LINK="$HOME/.local/bin/netaudit"
fi
if [[ -n "$LINK" ]]; then
    ok "Linked 'netaudit' command → $LINK"
    case ":$PATH:" in
        *":$(dirname "$LINK"):"*) : ;;
        *) warn "$(dirname "$LINK") isn't on your PATH — add it to use 'netaudit' directly." ;;
    esac
fi

# --- 7. Done ---
VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "$DEST/Contents/Info.plist" 2>/dev/null || echo "?")
ok "NetAudit $VERSION installed at $DEST"
echo
bold "Use it:"
echo "  netaudit          # one-shot safety verdict in the terminal"
echo "  netaudit gui      # open the menu-bar app + window"
echo "  open -a NetAudit  # or just launch the app (⌘Space → 'NetAudit')"

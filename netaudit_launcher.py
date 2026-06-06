"""NetAudit entry point — native macOS shell.

Architecture:
  - uvicorn runs the FastAPI app in a background daemon thread
  - rumps owns the main event loop (NSApp.run()) and the menu bar item
  - A WKWebView NSWindow renders the existing HTML UI, pointing at the
    local uvicorn server
  - The menu bar shows a status dot (🟢/🟡/🔴/⚪︎) reflecting the latest
    verdict from /api/network/check; auto-refreshes every 2 minutes
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import rumps
import uvicorn
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSMenu,
    NSMenuItem,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSURL, NSURLRequest
from PyObjCTools.AppHelper import callAfter
from WebKit import WKWebView, WKWebViewConfiguration

from config import API_HOST, API_PORT

SEVERITY_ICONS = {"trusted": "🟢", "ok": "🟢", "warn": "🟡", "danger": "🔴"}  # emoji fallback
# Maps a verdict severity → menu-bar glyph state (file stem). Custom glyph
# replaces the emoji dot; the colour carries the verdict.
GLYPH_FOR_SEVERITY = {"trusted": "ok", "ok": "ok", "warn": "warn", "danger": "danger"}
POLL_TIMEOUT_SECONDS = 30
POLL_INTERVAL_FALLBACK = 120  # used only if settings unreadable


def menubar_glyph_dir() -> Path:
    """Locate the bundled menu-bar glyphs in dev AND inside the py2app bundle."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent / "Resources" / "menubar"
    return Path(__file__).resolve().parent / "assets" / "menubar"


def glyph_path_for(severity: str | None) -> str | None:
    stem = GLYPH_FOR_SEVERITY.get(severity, "unknown")
    p = menubar_glyph_dir() / f"menubar_{stem}.png"
    return str(p) if p.exists() else None


def find_free_port(host: str, preferred: int, attempts: int = 10) -> int:
    for offset in range(attempts):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in {preferred}..{preferred + attempts - 1}")


def install_app_menu():
    """Install a minimal macOS app menu so standard shortcuts work — most
    importantly Cmd+Q (quit), Cmd+H (hide), Cmd+W (close window). Without
    this, those shortcuts do nothing because rumps doesn't set NSApp.mainMenu.
    """
    main = NSMenu.alloc().init()

    app_menu_item = NSMenuItem.alloc().init()
    main.addItem_(app_menu_item)
    app_menu = NSMenu.alloc().initWithTitle_("NetAudit")

    about = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "About NetAudit", "orderFrontStandardAboutPanel:", "")
    app_menu.addItem_(about)
    app_menu.addItem_(NSMenuItem.separatorItem())

    hide = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Hide NetAudit", "hide:", "h")
    app_menu.addItem_(hide)

    hide_others = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Hide Others", "hideOtherApplications:", "h")
    hide_others.setKeyEquivalentModifierMask_(1 << 19 | 1 << 20)  # opt+cmd
    app_menu.addItem_(hide_others)

    show_all = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Show All", "unhideAllApplications:", "")
    app_menu.addItem_(show_all)

    app_menu.addItem_(NSMenuItem.separatorItem())

    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit NetAudit", "terminate:", "q")
    app_menu.addItem_(quit_item)
    app_menu_item.setSubmenu_(app_menu)

    # Window menu (for Cmd+W close, Cmd+M minimize)
    window_menu_item = NSMenuItem.alloc().init()
    main.addItem_(window_menu_item)
    window_menu = NSMenu.alloc().initWithTitle_("Window")
    close = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Close Window", "performClose:", "w")
    window_menu.addItem_(close)
    minimize = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Minimize", "performMiniaturize:", "m")
    window_menu.addItem_(minimize)
    window_menu_item.setSubmenu_(window_menu)
    NSApp.setWindowsMenu_(window_menu)

    NSApp.setMainMenu_(main)


def wait_for_server(url: str, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


class NetAuditApp(rumps.App):
    def __init__(self, base_url: str):
        super().__init__("NetAudit", title="⚪︎", quit_button=None)
        self.base_url = base_url
        self.window: NSWindow | None = None
        self.webview: WKWebView | None = None

        self._status_item = rumps.MenuItem("Checking network…")
        self._refresh_item = rumps.MenuItem("Refresh Now", callback=self._on_refresh)
        self._report_item = rumps.MenuItem("Save Report…", callback=self._on_save_report, key="s")
        self.menu = [
            rumps.MenuItem("Open NetAudit…", callback=self._on_open, key="o"),
            None,
            self._status_item,
            None,
            self._refresh_item,
            self._report_item,
            rumps.MenuItem("Quit NetAudit", callback=rumps.quit_application, key="q"),
        ]

        # Show the neutral "checking" glyph immediately (avoids an emoji flash)
        self._set_status(None, "Checking network…")
        # Install the standard macOS app menu (gives us Cmd+Q, Cmd+W, Cmd+H)
        callAfter(install_app_menu)
        # Open the main window on launch
        callAfter(self._open_window)
        # Kick off the verdict-polling loop
        threading.Thread(target=self._poll_loop, daemon=True).start()

    # -------- Window --------

    def _open_window(self):
        if self.window is not None:
            self.window.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            return

        frame = NSMakeRect(140, 140, 1200, 820)
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskMiniaturizable
        )
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("NetAudit")
        # Hide instead of release when the user clicks the close button —
        # so we can reopen via the menu bar without rebuilding the view.
        self.window.setReleasedWhenClosed_(False)

        config = WKWebViewConfiguration.alloc().init()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(frame, config)
        self.window.setContentView_(self.webview)

        url = NSURL.URLWithString_(self.base_url)
        request = NSURLRequest.requestWithURL_(url)
        self.webview.loadRequest_(request)

        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    def _on_open(self, _sender):
        callAfter(self._open_window)

    # NSApplicationDelegate hook: clicking the dock icon when no window is
    # visible reopens the main window.
    def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, has_visible):
        if not has_visible:
            callAfter(self._open_window)
        return True

    # -------- Verdict polling --------

    def _on_refresh(self, _sender):
        threading.Thread(target=self._poll_once, daemon=True).start()

    # -------- Save report --------

    def _on_save_report(self, _sender):
        threading.Thread(target=self._save_report, daemon=True).start()

    def _save_report(self):
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/report", method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
        except Exception as e:
            callAfter(lambda: rumps.notification(
                "NetAudit", "Save failed", str(e)[:120]
            ))
            return
        path = data.get("path", "(unknown)")
        callAfter(lambda: rumps.notification(
            "NetAudit", "Report saved", path
        ))

    def _poll_loop(self):
        # Small initial delay so the window's first paint isn't competing
        time.sleep(2)
        while True:
            self._poll_once()
            # Re-read settings each iteration so changes apply without restart
            try:
                from settings import load as _load_settings
                interval = max(60, int(_load_settings()["safety_poll_minutes"]) * 60)
            except Exception:
                interval = POLL_INTERVAL_FALLBACK
            time.sleep(interval)

    def _poll_once(self):
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/api/network/check", timeout=POLL_TIMEOUT_SECONDS
            ) as r:
                data = json.loads(r.read())
        except Exception as e:
            self._set_status(None, f"Couldn't reach probe: {e}")
            return
        verdict = data.get("verdict") or {}
        headline = verdict.get("headline") or "Network checked"
        self._set_status(verdict.get("severity"), headline)

    def _set_status(self, severity: str | None, headline: str):
        # UI updates must hop to the main thread
        def update():
            path = glyph_path_for(severity)
            if path:
                # rumps.App's status-bar image is the `icon` property (NOT
                # set_icon — that's a MenuItem method). template stays off so the
                # verdict colour shows; the glyph's own padding sizes it nicely.
                self.icon = path
                self.title = ""  # show only the glyph, no emoji/text
            else:
                # No bundled glyph (e.g. dev before first build) — emoji fallback
                self.icon = None
                self.title = SEVERITY_ICONS.get(severity, "⚪︎")
            self._status_item.title = headline
        callAfter(update)


def run_gui():
    """Launch the menu-bar app + WKWebView window (the default for a double-click)."""
    port = find_free_port(API_HOST, API_PORT)
    url = f"http://{API_HOST}:{port}"
    print(f"NetAudit starting at {url}", flush=True)

    def run_server():
        from api import app
        uvicorn.run(app, host=API_HOST, port=port, log_level="warning")

    threading.Thread(target=run_server, daemon=True).start()

    if not wait_for_server(url, timeout=15):
        print("Server failed to start within 15s", file=sys.stderr)
        sys.exit(1)

    NetAuditApp(url).run()


# ---------- CLI (terminal `netaudit`) ----------

_SEV_ANSI = {"trusted": "\033[32m", "ok": "\033[32m", "warn": "\033[33m", "danger": "\033[31m"}


def _print_verdict(data: dict):
    color = sys.stdout.isatty()
    v = data.get("verdict") or {}
    sev = v.get("severity", "")
    c = _SEV_ANSI.get(sev, "") if color else ""
    rst = "\033[0m" if color and c else ""
    dim = "\033[2m" if color else ""
    ssid = f' on "{v["ssid"]}"' if v.get("ssid") else ""
    print(f"{c}● {v.get('headline', 'Network checked')}{rst}{ssid}")
    for s in v.get("sentences", []):
        print(f"  · {s}")
    # A compact line of the key signals.
    wifi = (data.get("wifi") or {}).get("encryption") or "?"
    spd = (data.get("speed") or {}).get("down_mbps")
    lat = ((data.get("latency") or {}).get("internet") or {}).get("avg_ms")
    dns = (data.get("dns") or {}).get("classification", {}).get("note") or ""
    facts = [f"Wi-Fi: {wifi}"]
    if spd is not None:
        facts.append(f"↓ {spd} Mbps")
    if lat is not None:
        facts.append(f"{round(lat)} ms")
    print(f"{dim}  {' · '.join(facts)}{rst}")
    if dns:
        print(f"{dim}  {dns}{rst}")


def run_cli(argv: list[str]) -> int:
    """`netaudit` / `netaudit verdict` — run the safety check, print to stdout."""
    as_json = "--json" in argv
    no_speed = "--no-speed" in argv
    import db
    import network
    db.init()  # CLI doesn't import api, so ensure tables exist
    try:
        from settings import load as _load
        speed = bool(_load().get("speed_test_enabled", True)) and not no_speed
    except Exception:
        speed = not no_speed
    if not as_json:
        print("Checking the network…", file=sys.stderr, flush=True)
    data = network.run_all(speed_test_enabled=speed)
    if as_json:
        print(json.dumps(data, default=str, indent=2))
    else:
        _print_verdict(data)
    sev = (data.get("verdict") or {}).get("severity")
    return 1 if sev == "danger" else 0  # non-zero exit on a danger verdict


def _print_usage():
    print(
        "NetAudit — is this Wi-Fi safe?\n\n"
        "Usage:\n"
        "  netaudit            Print a one-shot safety verdict for the current network\n"
        "  netaudit verdict    Same as above\n"
        "  netaudit --json     Verdict + all raw signals as JSON\n"
        "  netaudit --no-speed Skip the speed test (faster)\n"
        "  netaudit gui        Open the menu-bar app + window\n"
        "  netaudit help       Show this help\n"
    )


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("help", "-h", "--help"):
        _print_usage()
        return
    if argv and argv[0] in ("gui", "app"):
        return run_gui()
    if argv and argv[0] in ("verdict", "check"):
        return sys.exit(run_cli(argv[1:]))
    # No subcommand: a real terminal (tty) wants the CLI verdict; a Finder
    # double-click (no tty) wants the GUI.
    if sys.stdout.isatty():
        return sys.exit(run_cli(argv))
    return run_gui()


if __name__ == "__main__":
    main()

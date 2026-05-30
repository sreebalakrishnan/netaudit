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
import socket
import sys
import threading
import time
import urllib.request

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

SEVERITY_ICONS = {"ok": "🟢", "warn": "🟡", "danger": "🔴"}
POLL_INTERVAL_SECONDS = 120
POLL_TIMEOUT_SECONDS = 30


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
            time.sleep(POLL_INTERVAL_SECONDS)

    def _poll_once(self):
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/api/network/check", timeout=POLL_TIMEOUT_SECONDS
            ) as r:
                data = json.loads(r.read())
        except Exception as e:
            self._set_status("⚪︎", f"Couldn't reach probe: {e}")
            return
        verdict = data.get("verdict") or {}
        icon = SEVERITY_ICONS.get(verdict.get("severity"), "⚪︎")
        headline = verdict.get("headline") or "Network checked"
        self._set_status(icon, headline)

    def _set_status(self, icon: str, headline: str):
        # UI updates must hop to the main thread
        def update():
            self.title = icon
            self._status_item.title = headline
        callAfter(update)


def main():
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


if __name__ == "__main__":
    main()

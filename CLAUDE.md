# NetAudit — context for Claude sessions

> This file is auto-loaded by Claude Code on every session in this repo. **The public README is intentionally kept v0.1-era**; this file has the actual current state. If you're a fresh Claude session, read this first.

## What this is

A native macOS app for **café-Wi-Fi safety preflight**: walk in, look at the menu bar dot, see whether the network is safe + fast + private before doing anything sensitive on it. Plus a LAN device classifier (phones / TVs / computers / printers / IoT) with friendly icons.

Not a power-user network admin tool. The differentiation from Fing / iNet / NetSpot is the single-verdict plain-English UX.

## Current state (v0.9.0)

Working, shipped, runs as a real Mac app:

- 🟢/🟡/🔴 menu bar status dot (rumps) — auto-refreshes every 2 min
- WKWebView NSWindow renders the HTML UI (no browser tab)
- Safety check: Wi-Fi encryption, captive portal, DNS classification, public IP+geo, latency+jitter, speed test, ARP-spoof check, traceroute hops, VPN detection, Apple Private Relay availability
- Device scan: mDNS + SSDP + HTTP `<title>` probe + port profiling + mesh-node OUI matching
- Verdict synthesis: rolls all signals into one plain-English headline at the top of the page
- Personal-hotspot detection (`hotspot.py`): iOS (172.20.10.1 //28) / Android tethering / phone-OUI → a **trusted** verdict state that skips the public-Wi-Fi rules (no more red false-positive on your own hotspot). "Trust this network" persists by gateway MAC; real hazards still surface
- Settings modal (Cmd+,): theme (dark/light/system), scan subnet, refresh interval, speed test on/off, reports folder
- Save Report → JSON snapshot at `~/.netaudit/reports/`
- DMG installer (`./build.sh`) + one-line installer (`install.sh`)

## Architecture

```
NetAudit.app/Contents/MacOS/NetAudit
  └─ netaudit_launcher.py (main thread)
     ├─ uvicorn (background daemon thread) ─── serves FastAPI on 127.0.0.1:8001
     ├─ rumps (owns NSApp) ─────────────────── menu bar item, polling loop
     ├─ WKWebView NSWindow ─────────────────── renders templates/index.html
     └─ NSApp.mainMenu ─────────────────────── Cmd+Q/W/H/M shortcuts
```

| File | Owns |
|---|---|
| `api.py` | FastAPI routes (`/`, `/api/scan`, `/api/network/check`, `/api/settings`, `/api/report`, `/api/quit`) |
| `scanner.py` | LAN device discovery — ping sweep, ARP read, hostname resolve, vendor lookup, fingerprint orchestration |
| `fingerprint.py` | mDNS browsing, SSDP M-SEARCH, port probe, HTTP `<title>`+server probe, classifier rules, gateway detection |
| `network.py` | Safety probes — Wi-Fi, gateway, DNS, public IP, captive portal, latency, speed, traceroute, VPN, Private Relay, ARP anomaly, verdict synthesis (incl. trusted-network path) |
| `hotspot.py` | Personal-hotspot fingerprinting (route/ifconfig/arp/system_profiler) → confidence + evidence; stdlib-only, unit-tested (`test_hotspot.py`) |
| `db.py` | SQLite at `~/.netaudit/network_audit.db` (scans + devices + network_visits, incl. per-network `trusted` flag) |
| `settings.py` | User prefs at `~/.netaudit/config.json` (load/update/validate) |
| `config.py` | Env-var config (API_HOST, API_PORT, SCAN_SUBNET) — defaults overridable via `.env` |
| `netaudit_launcher.py` | Entry point. Starts uvicorn in a thread, sets up NSMenu, runs rumps app, opens WKWebView window |
| `templates/index.html` | Dark/light HTML UI (vanilla JS, no build step) |
| `setup.py` | py2app config |

## Build / run / test

```bash
# Run from source (development)
source venv_build/bin/activate
python netaudit_launcher.py

# Full build: bundle → ad-hoc sign → DMG → auto-update cask SHA
./build.sh

# Stop a running bundle
pkill -f NetAudit.app

# Smoke-test endpoints (port may be 8001 if 8000 is taken)
curl -sS http://127.0.0.1:8001/api/network/check | python3 -m json.tool
curl -sS http://127.0.0.1:8001/api/scan -X POST
```

Python 3.12 specifically — py2app 0.28.x doesn't support 3.13+. Install via `brew install python@3.12`.

## Key conventions (preserve these — they're hard-won)

- **Use absolute paths for system binaries.** Bare `arp` / `ping` / `route` etc. fail in the py2app subprocess env on Apple Silicon. Always `/usr/sbin/arp`, `/sbin/ping`, `/sbin/route`, `/usr/sbin/scutil`, `/usr/sbin/system_profiler`, `/usr/sbin/traceroute`.
- **All probes are rootless.** No raw sockets, no scapy, no sudo. ICMP via `subprocess.run(["/sbin/ping"])` is fine (setuid binary). ARP read via `/usr/sbin/arp -a` is fine (publicly readable).
- **ARP cache lag is real** — after `ping_latency` populates the cache, do a retry-with-prime if the gateway isn't there yet. See `network.run_all()`.
- **Verdict logic is rule-based, in `network.summarize()`** — bucket each signal into `danger` / `warn` / `good`, severity is the max. Plain English sentences, no jargon. UI shows verdict tile at top, technical tiles below.
- **UI tiles are plain English first** with click-to-expand for raw technical data. The user explicitly asked for this; don't regress to all-technical.
- **Settings round-trip via `/api/settings`** (GET/PUT JSON) and persist to `~/.netaudit/config.json`. Most settings take effect on next operation; theme is immediate.

## Distribution

- **No paid Apple Developer cert.** App is ad-hoc signed (py2app does this automatically on Apple Silicon; `build.sh` does an explicit `codesign --force --deep --sign -` pass too).
- **Gatekeeper warns on first launch** for direct DMG users. Workarounds in `INSTALL.md` (right-click → Open, or `xattr -dr com.apple.quarantine`).
- **The DMG ships as a GitHub Release asset** (switched from Hostinger hosting in v0.9.0). Each version is a tag `vX.Y.Z` with the DMG attached under **two names**: `NetAudit-X.Y.Z.dmg` (versioned, sha-pinned — what the cask points at) and `NetAudit.dmg` (stable — what `install.sh` pulls via `releases/latest/download/`). Cut a release with: `cp NetAudit-X.Y.Z.dmg NetAudit.dmg && gh release create vX.Y.Z NetAudit-X.Y.Z.dmg NetAudit.dmg` (the download URL uses the real filename, so the stable "latest" link needs an actual `NetAudit.dmg` copy, not just a label).
- **`install.sh` strips quarantine automatically** — `curl -fsSL https://netaudit.sreeb.dev/install.sh | bash` results in a silent install with no Gatekeeper prompt. The script itself is still served from the landing page, but it now downloads the DMG from `github.com/sreebalakrishnan/netaudit/releases/latest`.
- **Homebrew cask formula at `homebrew/Casks/netaudit.rb`** auto-updates version + SHA256 on every `./build.sh` and points at the GitHub Release download URL. The public tap repo `sreebalakrishnan/homebrew-netaudit` **is live** (`brew install sreebalakrishnan/netaudit/netaudit` works). Per-release: copy this cask into the tap's `Casks/` + push — see `HOMEBREW.md`. The tap cask must NOT carry a `verified:` param (url + homepage are both github.com → `brew audit` rejects it).
- **Hostinger-deployed sibling site at `netaudit.sreeb.dev`** lives in its own repo (`/Users/sreeb/Developer/netaudit.sreeb.dev`, GitHub `sreebalakrishnan/netaudit.sreeb.dev`). It still serves the landing page + `install.sh`, but the DMG is no longer hosted there — it lives on GitHub Releases.
- **Apple Developer cert + notarization steps documented in `SIGN.md`** for when/if the $99/year is paid.

## Don't do this

- **Don't rewrite as native SwiftUI** — explored and rejected. The Python ecosystem (zeroconf, mac-vendor-lookup, the entire networking stdlib) is too good to lose. The rumps + WKWebView wrapper IS native enough.
- **Don't pursue Mac App Store** without major rewrites — sandbox blocks subprocess to system_profiler/ping/traceroute/arp/scutil. Notarized direct download is the right path.
- **Don't rename the app** — naming research done; user chose to keep "NetAudit". Don't re-propose unless asked.
- **Don't bundle the DMG/build/dist/icns** in this repo — `.gitignore`'d intentionally. Build artifacts live in the sibling `netaudit.sreeb.dev` repo or get regenerated.
- **Don't auto-update README.md** — the user has intentionally kept it v0.1-style as a public-facing minimal description. Real status lives here in CLAUDE.md.
- **Don't bundle settings for things that take effect on app restart** without documenting it — most settings should be hot-reloadable. Theme switches immediately; subnet/speed-toggle on next operation; poll interval on next loop iteration.

## Open todos (drop-in candidates, not prioritized)

- Real landing page design for `netaudit.sreeb.dev` (user owns this; current site is a minimal placeholder)
- iPad vs iPhone disambiguation via mDNS TXT records (currently both classify as "iOS device")
- Live progress bar for the speed test instead of waiting ~5s for the result
- Per-app outbound traffic monitor (would need helper privileges — biggish lift)
- Reports list view + diff between two reports (so you can A/B compare cafés)

## Iteration pace

User prefers **one polish at a time, ship it, come back** — over batched multi-feature commits. Got this wrong in the v0.8 polish pass (six items in one commit); corrected since. See `feedback-iteration-pace` in user memory.

When picking a next step: ask "which one" with 2-4 concrete options, then ship it as a small focused commit. Don't fan out.

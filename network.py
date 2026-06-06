"""Network safety / quality probes for the café-Wi-Fi use case.

All checks are rootless. Public IP + geo + speed test require outbound
internet, so they may report 'unavailable' when behind a captive portal.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.error import URLError

import db  # manual "trust this network" lookups, keyed by gateway MAC
import hotspot  # personal-hotspot fingerprinting → trusted networks
import scanner  # for read_arp_table


# ---------- Wi-Fi info (SSID, encryption) ----------

def get_wifi_info() -> dict:
    """Get current Wi-Fi SSID and security via system_profiler (no sudo)."""
    info: dict = {"ssid": None, "encryption": None, "channel": None, "rssi": None}
    try:
        out = subprocess.check_output(
            ["/usr/sbin/system_profiler", "SPAirPortDataType", "-detailLevel", "basic"],
            text=True, timeout=10,
        )
    except Exception:
        return info

    # Parse the "Current Network Information" block
    lines = out.splitlines()
    in_current = False
    indent_current = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "Current Network Information" in stripped:
            in_current = True
            indent_current = len(line) - len(line.lstrip())
            continue
        if not in_current:
            continue
        # The SSID is the first indented line after "Current Network Information"
        if info["ssid"] is None and stripped.endswith(":") and not stripped.startswith("PHY"):
            indent = len(line) - len(line.lstrip())
            if indent > (indent_current or 0):
                info["ssid"] = stripped.rstrip(":")
                continue
        if "Security:" in stripped:
            info["encryption"] = stripped.split(":", 1)[1].strip()
        elif "Channel:" in stripped:
            info["channel"] = stripped.split(":", 1)[1].strip()
        elif "Signal / Noise:" in stripped:
            info["rssi"] = stripped.split(":", 1)[1].strip()
        elif info["ssid"] and info["encryption"] and stripped == "":
            # End of current-network block
            break

    return info


# ---------- Gateway + DNS ----------

def get_gateway() -> str | None:
    try:
        out = subprocess.check_output(["/sbin/route", "-n", "get", "default"], text=True, timeout=2)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("gateway:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def get_dns_resolvers() -> list[str]:
    """Read configured DNS resolvers via scutil --dns."""
    resolvers: list[str] = []
    try:
        out = subprocess.check_output(["/usr/sbin/scutil", "--dns"], text=True, timeout=2)
    except Exception:
        return resolvers
    # Take the first 'resolver #1' nameservers (active interface)
    in_first = False
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("resolver #1"):
            in_first = True
            continue
        if line.startswith("resolver #") and in_first:
            break
        if in_first and line.startswith("nameserver["):
            ns = line.split(":", 1)[1].strip()
            if ns not in resolvers and not ns.startswith("fe80:") and ":" not in ns:
                resolvers.append(ns)
    return resolvers


KNOWN_DNS = {
    "1.1.1.1": "Cloudflare", "1.0.0.1": "Cloudflare",
    "8.8.8.8": "Google", "8.8.4.4": "Google",
    "9.9.9.9": "Quad9", "149.112.112.112": "Quad9",
    "208.67.222.222": "OpenDNS", "208.67.220.220": "OpenDNS",
}


def classify_dns(resolvers: list[str], gateway: str | None) -> dict:
    if not resolvers:
        return {"status": "unknown", "note": "Could not read resolver config"}
    first = resolvers[0]
    if first == gateway:
        return {"status": "gateway", "note": f"DNS via gateway ({first}) — typical home/café setup"}
    if first in KNOWN_DNS:
        return {"status": "public", "note": f"Public resolver: {KNOWN_DNS[first]} ({first})"}
    # Private-network DNS that isn't the gateway → unusual
    try:
        import ipaddress
        ip = ipaddress.IPv4Address(first)
        if ip.is_private:
            return {"status": "private-other", "note": f"Private DNS {first} (not the gateway) — verify it's expected"}
    except Exception:
        pass
    return {"status": "external", "note": f"External resolver {first} — unfamiliar; verify before sensitive use"}


# ---------- Public IP + geo ----------

def get_public_ip() -> dict:
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=4) as r:
            data = json.loads(r.read().decode())
        return {
            "ip": data.get("ip"),
            "city": data.get("city"),
            "region": data.get("region"),
            "country": data.get("country"),
            "org": data.get("org"),
        }
    except Exception as e:
        return {"error": str(e)}


# ---------- Captive portal ----------

def check_captive_portal() -> dict:
    """Use Apple's well-known endpoint to detect captive portals."""
    url = "http://captive.apple.com/hotspot-detect.html"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CaptiveNetworkSupport/1.0 wispr"})
        with urllib.request.urlopen(req, timeout=4) as r:
            body = r.read().decode(errors="ignore")
            final_url = r.geturl()
    except URLError as e:
        return {"status": "no-internet", "note": f"No outbound HTTP ({e.reason})"}
    except Exception as e:
        return {"status": "error", "note": str(e)}
    if "Success" in body and final_url == url:
        return {"status": "open", "note": "Internet reachable, no captive portal"}
    return {"status": "captive", "note": f"Captive portal detected (final URL: {final_url})"}


# ---------- Latency ----------

_PING_STATS_RE = re.compile(
    r"min/avg/max(?:/stddev)? = ([\d.]+)/([\d.]+)/([\d.]+)(?:/([\d.]+))?"
)


def ping_latency(host: str, count: int = 4) -> dict:
    try:
        out = subprocess.check_output(
            ["/sbin/ping", "-c", str(count), "-q", host],
            text=True, timeout=count + 4,
        )
    except subprocess.TimeoutExpired:
        return {"host": host, "error": "timeout"}
    except subprocess.CalledProcessError as e:
        return {"host": host, "error": "unreachable", "output": e.output[:200] if e.output else ""}
    except Exception as e:
        return {"host": host, "error": str(e)}
    loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    stats = _PING_STATS_RE.search(out)
    return {
        "host": host,
        "avg_ms": float(stats.group(2)) if stats else None,
        "jitter_ms": float(stats.group(4)) if stats and stats.group(4) else None,
        "loss_pct": float(loss_match.group(1)) if loss_match else None,
    }


# ---------- Speed test ----------

SPEED_ENDPOINTS = [
    "https://speed.cloudflare.com/__down?bytes={n}",
    "https://proof.ovh.net/files/10Mb.dat",
    "http://ipv4.download.thinkbroadband.com/5MB.zip",
]


def speed_test_stream(bytes_to_download: int = 5_000_000, chunk_size: int = 65536):
    """Generator: yield progress dicts as bytes are downloaded.

    Last yielded dict has done=True (or error key if all endpoints failed).
    Throttles progress events to one every ~150ms so SSE doesn't flood.
    """
    headers = {"User-Agent": "NetAudit/0.9 (network audit)"}
    last_err = None
    for tmpl in SPEED_ENDPOINTS:
        url = tmpl.format(n=bytes_to_download)
        endpoint_host = url.split("/")[2]
        try:
            req = urllib.request.Request(url, headers=headers)
            start = time.monotonic()
            total = 0
            last_emit = start
            with urllib.request.urlopen(req, timeout=15) as r:
                while True:
                    chunk = r.read(chunk_size)
                    if not chunk:
                        break
                    total += len(chunk)
                    now = time.monotonic()
                    elapsed = now - start
                    if now - last_emit >= 0.15:
                        last_emit = now
                        yield {
                            "bytes": total,
                            "elapsed_s": round(elapsed, 2),
                            "down_mbps": round((total * 8) / 1_000_000 / elapsed, 1) if elapsed > 0.001 else 0,
                            "endpoint": endpoint_host,
                            "done": False,
                        }
                    if total >= bytes_to_download * 2:
                        break
            elapsed = time.monotonic() - start
            if elapsed > 0.001 and total > 0:
                yield {
                    "bytes": total,
                    "elapsed_s": round(elapsed, 2),
                    "down_mbps": round((total * 8) / 1_000_000 / elapsed, 1),
                    "endpoint": endpoint_host,
                    "done": True,
                }
                return
        except Exception as e:
            last_err = str(e)
            continue
    yield {"error": last_err or "all endpoints failed", "done": True}


def speed_test(bytes_to_download: int = 5_000_000) -> dict:
    """Try each speed-test endpoint until one works. Report down Mbps."""
    headers = {"User-Agent": "NetAudit/0.3 (network audit)"}
    last_err = None
    for tmpl in SPEED_ENDPOINTS:
        url = tmpl.format(n=bytes_to_download)
        try:
            req = urllib.request.Request(url, headers=headers)
            start = time.monotonic()
            with urllib.request.urlopen(req, timeout=15) as r:
                total = 0
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    # Cap at requested size in case endpoint is bigger
                    if total >= bytes_to_download * 2:
                        break
            elapsed = time.monotonic() - start
            if elapsed < 0.001 or total == 0:
                continue
            return {
                "endpoint": url.split("/")[2],
                "bytes": total,
                "elapsed_s": round(elapsed, 2),
                "down_mbps": round((total * 8) / 1_000_000 / elapsed, 1),
            }
        except Exception as e:
            last_err = str(e)
            continue
    return {"error": last_err or "all endpoints failed"}


# ---------- Traceroute / hops ----------

_HOP_RE = re.compile(r"^\s*(\d+)\s+(\S+)\s+([\d.]+)\s*ms")


def traceroute_hops(host: str = "1.1.1.1", max_hops: int = 12) -> dict:
    """Run a single-probe traceroute, return hop list."""
    try:
        out = subprocess.check_output(
            ["/usr/sbin/traceroute", "-n", "-w", "1", "-q", "1", "-m", str(max_hops), host],
            text=True, timeout=max_hops + 4, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return {"host": host, "error": str(e), "hops": []}
    hops: list[dict] = []
    reached = False
    for line in out.splitlines():
        m = _HOP_RE.match(line)
        if m:
            hop = {"n": int(m.group(1)), "ip": m.group(2), "rtt_ms": float(m.group(3))}
            hops.append(hop)
            if hop["ip"] == host:
                reached = True
        elif re.match(r"^\s*\d+\s+\*", line):
            n = int(line.strip().split()[0])
            hops.append({"n": n, "ip": None, "rtt_ms": None})
    return {"host": host, "hops": hops, "count": len(hops), "reached": reached}


# ---------- VPN detection ----------

VPN_PREFIXES = ("utun", "ppp", "ipsec", "tun", "tap")


def detect_vpn() -> dict:
    """Check the default route's interface — if it's a VPN tunnel, report it."""
    try:
        out = subprocess.check_output(
            ["/sbin/route", "-n", "get", "default"], text=True, timeout=2,
        )
    except Exception:
        return {"active": False, "interface": None}
    iface = None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("interface:"):
            iface = s.split(":", 1)[1].strip()
            break
    if iface and iface.startswith(VPN_PREFIXES):
        return {"active": True, "interface": iface}
    return {"active": False, "interface": iface}


# ---------- Apple Private Relay ----------

def detect_private_relay() -> dict:
    """Check if iCloud+ Private Relay is reachable from this host.

    PR is per-app (Safari + Mail). We can only detect availability, not
    whether a given app actually uses it.
    """
    try:
        socket.setdefaulttimeout(2.0)
        socket.gethostbyname("mask.icloud.com")
        mask_resolves = True
    except Exception:
        mask_resolves = False
    return {
        "available": mask_resolves,
        "note": "Safari and Mail use it when iCloud+ Private Relay is on"
                if mask_resolves else "Not reachable from this network",
    }


# ---------- ARP-spoof check ----------

def arp_anomalies(arp_table: dict[str, str], gateway: str | None) -> dict:
    """Look for duplicate MACs, locally-administered gateway MAC, etc."""
    findings: list[str] = []
    severity = "ok"

    # Group IPs by MAC
    by_mac: dict[str, list[str]] = {}
    for ip, mac in arp_table.items():
        by_mac.setdefault(mac, []).append(ip)

    # Duplicate MACs (same MAC on multiple IPs) — classic ARP-poison signal
    for mac, ips in by_mac.items():
        if len(ips) > 1:
            findings.append(f"Same MAC {mac} bound to multiple IPs: {', '.join(sorted(ips))}")
            severity = "warn"

    # Gateway MAC sanity
    if gateway and gateway in arp_table:
        gw_mac = arp_table[gateway]
        first_octet = int(gw_mac.split(":")[0], 16)
        # Locally-administered (2nd-least-significant bit of first octet)
        if first_octet & 0x02:
            findings.append(f"Gateway MAC {gw_mac} has the locally-administered bit set (unusual for a real router)")
            severity = "warn"
    elif gateway:
        findings.append(f"Gateway {gateway} not in ARP table — could not verify MAC")

    return {
        "severity": severity,
        "findings": findings or ["No ARP anomalies detected"],
    }


# ---------- Verdict ----------

def _clean_ssid(ssid: str | None) -> str | None:
    """Normalize an SSID for display: blank, whitespace, or redacted → None.

    macOS redacts the SSID to '<redacted>' without Location access, and
    system_profiler can momentarily return a whitespace-only name mid-scan —
    both should render as no-SSID rather than an empty `on ""` in the header.
    """
    if not ssid:
        return None
    ssid = ssid.strip()
    if not ssid or ssid == "<redacted>":
        return None
    return ssid


def _trusted_dangers(data: dict) -> list[str]:
    """Real danger signals we still surface even on a trusted network.

    We suppress the *public-Wi-Fi* heuristics on a hotspot (rogue-AP MAC check,
    weak-encryption nags, "you don't control this network"), but genuine hazards
    — an actually open network, a DNS resolver that could be redirecting you —
    must still come through, reframed for the hotspot context.
    """
    out: list[str] = []
    enc = ((data.get("wifi") or {}).get("encryption") or "").lower()
    if enc and ("open" in enc or "none" in enc):
        out.append("This network has no Wi-Fi password — anyone nearby could join. "
                   "If it's your hotspot, turn the password on in your phone's settings.")
    dns = (data.get("dns") or {}).get("classification") or {}
    if dns.get("status") in ("private-other", "external"):
        out.append("DNS is going somewhere unexpected — could be redirecting your traffic. "
                   "Verify before signing into anything sensitive.")
    return out


_CATEGORY_HEADLINE = {
    "home": "Home network",
    "office": "Office network",
    "trusted": "Trusted network",
}


def _summarize_trusted(data: dict, hs, manual: bool) -> dict:
    """Verdict for a trusted network (personal hotspot, or user-labeled).

    Neutral/green TRUSTED state. Skips the public-Wi-Fi rules; explains why it's
    trusted; keeps the device count informational. Real dangers (see
    _trusted_dangers) are still surfaced and bump severity to red.
    """
    category = data.get("net_category")
    label = _clean_ssid(data.get("net_label"))  # reuse blank/whitespace cleanup
    kind = getattr(hs, "kind", None)

    # Headline priority: a user-set category wins; else hotspot; else generic.
    if category in _CATEGORY_HEADLINE:
        headline = _CATEGORY_HEADLINE[category]
        if label:
            headline += f" — {label}"
    elif kind is hotspot.HotspotKind.APPLE:
        headline = "Personal Hotspot — your own device"
    elif kind is hotspot.HotspotKind.ANDROID:
        headline = "Phone hotspot — your own device"
    elif hs is not None and hs.is_trusted:
        headline = "Personal hotspot — your own device"
    else:
        headline = "Trusted network — you marked this one safe"

    sentences: list[str] = []
    if category == "home":
        sentences.append("Your home network — public-Wi-Fi warnings are turned off here.")
    elif category == "office":
        sentences.append("Your office network — public-Wi-Fi warnings are turned off here.")
    elif category == "trusted":
        sentences.append("You've marked this network as trusted, so the public-Wi-Fi "
                         "warnings are turned off here.")
    elif hs is not None and hs.evidence:
        # Lead with the strongest piece of hotspot evidence, in plain English.
        sentences.append("This is your own device: " + hs.evidence[0] + ".")
    elif manual:
        sentences.append("You've marked this network as trusted, so the public-Wi-Fi "
                         "warnings are turned off here.")

    # Device count — informational, not a concern, on your own network.
    n = data.get("device_count")
    if n is not None:
        if n <= 1:
            sentences.append("Only your devices should be here — none other seen.")
        else:
            sentences.append(f"Only your devices should be here — {n} seen.")

    dangers = _trusted_dangers(data)
    if dangers:
        severity = "danger"
        headline = headline + " — but something looks off"
        sentences = dangers + sentences
    else:
        severity = "trusted"

    ssid = _clean_ssid((data.get("wifi") or {}).get("ssid"))
    if ssid is None and hs is not None:
        ssid = _clean_ssid(hs.ssid)

    if category in _CATEGORY_HEADLINE:
        trust_source = "category"
    elif hs is not None and hs.is_trusted:
        trust_source = "hotspot"
    else:
        trust_source = "manual"

    return {
        "severity": severity,
        "headline": headline,
        "sentences": sentences[:5],
        "ssid": ssid,
        "trusted": True,
        "category": category,
        "label": label,
        "hotspot": hs.as_dict() if hs is not None else None,
        "trust_source": trust_source,
    }


def summarize(data: dict) -> dict:
    """Roll the raw safety signals into a plain-English verdict.

    Returns {severity, headline, sentences, ssid} — UI shows this as a
    big headline tile above the technical signal tiles. When the network is a
    personal hotspot or user-trusted, returns a TRUSTED verdict instead.
    """
    hs = data.get("hotspot")
    manual = bool(data.get("manual_trusted"))
    if manual or (hs is not None and hs.is_trusted):
        return _summarize_trusted(data, hs, manual)

    danger: list[str] = []
    warn: list[str] = []
    good: list[str] = []

    # ---- Encryption ----
    wifi = data.get("wifi") or {}
    enc = (wifi.get("encryption") or "").lower()
    if not enc:
        warn.append("Couldn't read the Wi-Fi encryption — verify before signing into anything.")
    elif "open" in enc or "none" in enc:
        danger.append("No password on this network — anyone nearby can see your traffic.")
    elif "wep" in enc or enc.startswith("wpa ") or enc == "wpa personal":
        warn.append("Older Wi-Fi encryption — okay for browsing, avoid sensitive accounts without a VPN.")
    else:
        good.append("Encrypted Wi-Fi.")

    # ---- Internet / captive portal ----
    portal = data.get("captive_portal") or {}
    ps = portal.get("status")
    if ps == "captive":
        warn.append("Sign-in page is in the way — log in first, then re-check.")
    elif ps == "no-internet":
        danger.append("No internet reaching out — you're connected but offline.")

    # ---- ARP / tampering ----
    arp = data.get("arp_check") or {}
    if arp.get("severity") == "warn":
        first = (arp.get("findings") or [""])[0]
        if "locally-administered" in first:
            danger.append("The gateway's MAC looks fake — possibly a rogue access point.")
        else:
            danger.append("Network tampering signs detected — avoid logging into sensitive accounts.")
    else:
        good.append("No tampering signs.")

    # ---- DNS ----
    dns = (data.get("dns") or {}).get("classification") or {}
    if dns.get("status") in ("private-other", "external"):
        warn.append("Unusual DNS resolver — could be redirecting where you're going.")

    # ---- Speed ----
    spd = data.get("speed") or {}
    mbps = spd.get("down_mbps")
    if mbps is not None:
        if mbps < 2:
            warn.append("Very slow — pages will crawl, video won't work.")
        elif mbps < 8:
            good.append("Fine for browsing and SD video.")
        elif mbps < 25:
            good.append("Fast enough for HD video.")
        else:
            good.append("Plenty fast — 4K and big downloads no problem.")

    # ---- Latency + jitter (call quality) ----
    inet = (data.get("latency") or {}).get("internet") or {}
    lat = inet.get("avg_ms")
    jit = inet.get("jitter_ms")
    if lat is not None:
        if lat > 250 or (jit is not None and jit > 40):
            warn.append("Real-time apps will struggle — calls and games will lag.")
        elif lat > 120 or (jit is not None and jit > 20):
            good.append("Okay for calls — minor stutter possible.")
        else:
            good.append("Snappy response — calls and games should feel smooth.")

    # ---- VPN (informational, not a concern) ----
    vpn = data.get("vpn") or {}
    if vpn.get("active"):
        iface = vpn.get("interface") or "tunnel"
        good.append(f"VPN is on — your traffic exits through a tunnel ({iface}).")

    # ---- Hops (informational unless excessive) ----
    hops = data.get("hops") or {}
    n_hops = hops.get("count")
    if n_hops:
        if n_hops > 15:
            warn.append(f"Indirect route to the internet ({n_hops} hops) — could be a transit detour.")
        elif n_hops <= 6 and hops.get("reached"):
            good.append(f"Direct route to the internet ({n_hops} hops).")

    # ---- Severity rollup ----
    if danger:
        severity = "danger"
        headline = "Be careful on this network."
    elif warn:
        severity = "warn"
        headline = "Mostly fine, with caveats."
    else:
        severity = "ok"
        headline = "This network looks safe."

    # Order: danger > warn > positives — show concerns first
    sentences = danger + warn + good[:3]
    ssid = _clean_ssid(wifi.get("ssid"))

    return {
        "severity": severity,
        "headline": headline,
        "sentences": sentences[:5],
        "ssid": ssid,
    }


# ---------- Orchestrator ----------

def _prime_arp(gateway: str | None):
    """Ping the gateway so it's in the ARP cache when we read it."""
    if not gateway:
        return
    try:
        subprocess.run(
            ["/sbin/ping", "-c", "1", "-W", "300", gateway],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
    except Exception:
        pass


def run_all(speed_test_enabled: bool = True) -> dict:
    """Run every check in parallel; ~5-7s end-to-end."""
    gateway = get_gateway()

    with ThreadPoolExecutor(max_workers=10) as ex:
        f_wifi = ex.submit(get_wifi_info)
        f_dns = ex.submit(get_dns_resolvers)
        f_pub = ex.submit(get_public_ip)
        f_portal = ex.submit(check_captive_portal)
        f_gw_lat = ex.submit(ping_latency, gateway, 4) if gateway else None
        f_inet_lat = ex.submit(ping_latency, "1.1.1.1", 4)
        f_speed = ex.submit(speed_test, 5_000_000) if speed_test_enabled else None
        f_hops = ex.submit(traceroute_hops, "1.1.1.1", 12)
        f_vpn = ex.submit(detect_vpn)
        f_pr = ex.submit(detect_private_relay)

        wifi = f_wifi.result()
        resolvers = f_dns.result()
        public = f_pub.result()
        portal = f_portal.result()
        gw_lat = f_gw_lat.result() if f_gw_lat else {"host": None, "error": "no gateway"}
        inet_lat = f_inet_lat.result()
        speed = f_speed.result() if f_speed else {"skipped": True, "note": "Disabled in Settings"}
        hops = f_hops.result()
        vpn = f_vpn.result()
        relay = f_pr.result()

    # Read ARP AFTER the parallel pings. Retry-with-prime if the gateway
    # didn't make it in (ARP cache can lag behind ping completion).
    arp_table = scanner.read_arp_table()
    if gateway and gateway not in arp_table:
        _prime_arp(gateway)
        time.sleep(0.3)
        arp_table = scanner.read_arp_table()

    # Is this a trusted network? Personal hotspot (auto) or user-marked (manual).
    # Decide first — a trusted verdict skips the public-Wi-Fi rules below.
    hs = hotspot.detect_hotspot()
    gw_mac = arp_table.get(gateway) if gateway else None
    visit = db.get_visit(gw_mac) if gw_mac else None
    manual_trusted = bool(visit and visit.get("trusted"))

    result = {
        "wifi": wifi,
        "gateway": gateway,
        "dns": {
            "resolvers": resolvers,
            "classification": classify_dns(resolvers, gateway),
        },
        "public": public,
        "captive_portal": portal,
        "latency": {"gateway": gw_lat, "internet": inet_lat},
        "speed": speed,
        "arp_check": arp_anomalies(arp_table, gateway),
        "hops": hops,
        "vpn": vpn,
        "private_relay": relay,
        # Extras consumed by summarize(); hotspot stays an object until after.
        "hotspot": hs,
        "manual_trusted": manual_trusted,
        "net_category": (visit or {}).get("category"),
        "net_label": (visit or {}).get("label"),
        "device_count": len(arp_table),
    }
    result["verdict"] = summarize(result)
    # Make hotspot JSON-serializable for the API/report now that summarize is done.
    result["hotspot"] = hs.as_dict()
    return result

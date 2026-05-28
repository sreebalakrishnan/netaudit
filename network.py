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

_PING_AVG_RE = re.compile(r"min/avg/max(?:/stddev)? = [\d.]+/([\d.]+)/")


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
    avg_match = _PING_AVG_RE.search(out)
    return {
        "host": host,
        "avg_ms": float(avg_match.group(1)) if avg_match else None,
        "loss_pct": float(loss_match.group(1)) if loss_match else None,
    }


# ---------- Speed test ----------

SPEED_ENDPOINTS = [
    "https://speed.cloudflare.com/__down?bytes={n}",
    "https://proof.ovh.net/files/10Mb.dat",
    "http://ipv4.download.thinkbroadband.com/5MB.zip",
]


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


def run_all() -> dict:
    """Run every check in parallel; ~5-7s end-to-end."""
    gateway = get_gateway()

    with ThreadPoolExecutor(max_workers=7) as ex:
        f_wifi = ex.submit(get_wifi_info)
        f_dns = ex.submit(get_dns_resolvers)
        f_pub = ex.submit(get_public_ip)
        f_portal = ex.submit(check_captive_portal)
        f_gw_lat = ex.submit(ping_latency, gateway, 4) if gateway else None
        f_inet_lat = ex.submit(ping_latency, "1.1.1.1", 4)
        f_speed = ex.submit(speed_test, 5_000_000)

        wifi = f_wifi.result()
        resolvers = f_dns.result()
        public = f_pub.result()
        portal = f_portal.result()
        gw_lat = f_gw_lat.result() if f_gw_lat else {"host": None, "error": "no gateway"}
        inet_lat = f_inet_lat.result()
        speed = f_speed.result()

    # Read ARP AFTER the parallel pings. Retry-with-prime if the gateway
    # didn't make it in (ARP cache can lag behind ping completion).
    arp_table = scanner.read_arp_table()
    if gateway and gateway not in arp_table:
        _prime_arp(gateway)
        time.sleep(0.3)
        arp_table = scanner.read_arp_table()

    return {
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
    }

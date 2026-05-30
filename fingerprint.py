"""Device fingerprinting via mDNS, SSDP, NetBIOS and TCP port probes.

All discovery is rootless: multicast UDP listening + connect-scan TCP.
"""
from __future__ import annotations

import re
import socket
import ssl
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

# Service types we care about (mDNS / DNS-SD)
MDNS_SERVICES = [
    "_apple-mobdev2._tcp.local.",
    "_companion-link._tcp.local.",
    "_airplay._tcp.local.",
    "_raop._tcp.local.",
    "_homekit._tcp.local.",
    "_hap._tcp.local.",
    "_googlecast._tcp.local.",
    "_sonos._tcp.local.",
    "_spotify-connect._tcp.local.",
    "_printer._tcp.local.",
    "_ipp._tcp.local.",
    "_ipps._tcp.local.",
    "_pdl-datastream._tcp.local.",
    "_workstation._tcp.local.",
    "_smb._tcp.local.",
    "_afpovertcp._tcp.local.",
    "_ssh._tcp.local.",
    "_amzn-wplay._tcp.local.",
    "_hue._tcp.local.",
    "_meshcop._udp.local.",
    "_nanoleafapi._tcp.local.",
    "_googlerpc._tcp.local.",
    "_googlezone._tcp.local.",
]

# TCP ports to probe per device (fast)
PORT_PROBES = [22, 80, 443, 445, 548, 1883, 5000, 5353, 7000, 8008, 8009, 8060, 9100, 62078]

# Friendly labels for port hits
PORT_LABEL = {
    22: "ssh", 80: "http", 443: "https", 445: "smb", 548: "afp",
    1883: "mqtt", 5000: "upnp", 5353: "mdns", 7000: "airplay",
    8008: "chromecast", 8009: "chromecast-tls", 8060: "roku-ecp",
    9100: "printer-raw", 62078: "ios-lockdownd",
}


@dataclass
class Signals:
    services: set[str] = field(default_factory=set)
    mdns_hostnames: set[str] = field(default_factory=set)
    ssdp_servers: set[str] = field(default_factory=set)
    open_ports: set[int] = field(default_factory=set)
    http_titles: set[str] = field(default_factory=set)


# ---------- mDNS ----------

def discover_mdns(timeout: float = 5.0) -> dict[str, Signals]:
    """Browse a fixed list of service types, collect by responder IP."""
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except ImportError:
        return {}

    results: dict[str, Signals] = {}
    zc = Zeroconf()

    class Listener:
        def add_service(self, zc, type_, name):
            try:
                info = zc.get_service_info(type_, name, timeout=1500)
            except Exception:
                return
            if not info:
                return
            short_type = (
                type_.replace(".local.", "")
                .replace("._tcp", "-tcp")
                .replace("._udp", "-udp")
                .lstrip("_")
            )
            for addr in info.parsed_addresses():
                if ":" in addr:
                    continue
                sig = results.setdefault(addr, Signals())
                sig.services.add(short_type)
                if info.server:
                    sig.mdns_hostnames.add(info.server.rstrip("."))

        def update_service(self, *a, **kw): pass
        def remove_service(self, *a, **kw): pass

    listener = Listener()
    browsers = [ServiceBrowser(zc, st, listener) for st in MDNS_SERVICES]

    time.sleep(timeout)

    for b in browsers:
        try: b.cancel()
        except Exception: pass
    zc.close()
    return results


# ---------- SSDP ----------

SSDP_REQUEST = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: ssdp:all\r\n\r\n"
).encode()


def discover_ssdp(timeout: float = 3.0) -> dict[str, Signals]:
    """Send an SSDP M-SEARCH, collect Server: headers by sender IP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(0.5)
    try:
        s.sendto(SSDP_REQUEST, ("239.255.255.250", 1900))
    except Exception:
        s.close()
        return {}

    results: dict[str, Signals] = {}
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, (ip, _port) = s.recvfrom(4096)
        except socket.timeout:
            continue
        except Exception:
            break
        sig = results.setdefault(ip, Signals())
        for line in data.decode(errors="ignore").splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                if k.strip().upper() == "SERVER":
                    sig.ssdp_servers.add(v.strip())
    s.close()
    return results


# ---------- TCP port probe ----------

def _port_open(ip: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((ip, port)) == 0
    except Exception:
        return False


def probe_ports(ip: str, ports: list[int] = PORT_PROBES) -> set[int]:
    open_set: set[int] = set()
    with ThreadPoolExecutor(max_workers=len(ports)) as ex:
        for port, ok in zip(ports, ex.map(lambda p: _port_open(ip, p), ports)):
            if ok:
                open_set.add(port)
    return open_set


# ---------- HTTP title probe ----------

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_REFRESH_RE = re.compile(
    r'<meta\s+http-equiv\s*=\s*"?refresh"?\s+content\s*=\s*"\s*\d+\s*;\s*URL=([^"]+)"',
    re.IGNORECASE,
)
_HTTP_UA = "NetAudit/0.6 (network audit)"


def _http_get(url: str, timeout: float) -> tuple[str, str | None]:
    """Fetch URL, return (body, server_header). Ignore TLS errors."""
    ctx = ssl._create_unverified_context() if url.startswith("https://") else None
    req = urllib.request.Request(url, headers={"User-Agent": _HTTP_UA})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        server = r.headers.get("Server")
        body = r.read(16384).decode(errors="ignore")
    return body, server


def http_title(ip: str, port: int, timeout: float = 1.5) -> tuple[str | None, str | None]:
    """Return (title, server_header). Follow one meta-refresh if root has no title."""
    scheme = "https" if port == 443 else "http"
    root = f"{scheme}://{ip}:{port}/"
    try:
        body, server = _http_get(root, timeout)
    except Exception:
        return None, None
    m = _TITLE_RE.search(body)
    if m:
        return _clean_title(m.group(1)), server
    # No <title> at root — follow a meta-refresh if there is one
    rm = _META_REFRESH_RE.search(body)
    if rm:
        next_url = rm.group(1)
        if next_url.startswith("/"):
            next_url = f"{scheme}://{ip}:{port}{next_url}"
        elif not next_url.startswith("http"):
            next_url = f"{scheme}://{ip}:{port}/{next_url}"
        try:
            body2, server2 = _http_get(next_url, timeout)
            m2 = _TITLE_RE.search(body2)
            if m2:
                return _clean_title(m2.group(1)), server or server2
            return None, server or server2
        except Exception:
            pass
    return None, server


def _clean_title(raw: str) -> str | None:
    title = re.sub(r"\s+", " ", raw).strip()
    return title[:120] or None


def probe_http_titles(ip: str, open_ports: set[int]) -> set[str]:
    """Probe whichever of 80/443 are open. Return de-duped title + server strings.

    Server header values are prefixed with 'srv:' so the classifier can tell them
    apart from <title> strings.
    """
    out: set[str] = set()
    for port in (80, 443):
        if port not in open_ports:
            continue
        title, server = http_title(ip, port)
        if title:
            out.add(title)
        if server:
            out.add(f"srv:{server}")
    return out


# ---------- Classifier ----------

def _has_any(haystack: set[str], needles: list[str]) -> bool:
    return any(any(n.lower() in h.lower() for h in haystack) for n in needles)


def classify(
    ip: str,
    mac: str | None,
    hostname: str | None,
    vendor: str | None,
    signals: Signals,
    gateway_ip: str | None,
) -> dict:
    """Rule-based classification. Returns dict with type/brand/model/confidence."""
    services = signals.services
    servers = signals.ssdp_servers
    ports = signals.open_ports
    hn = (hostname or "").lower()
    all_hn = hn + " " + " ".join(s.lower() for s in signals.mdns_hostnames)

    # ---- Router (high confidence) ----
    if gateway_ip and ip == gateway_ip:
        brand = vendor
        if _has_any(servers, ["eero"]) or "eero" in all_hn:
            brand = "eero"
        elif _has_any(servers, ["asus"]): brand = "ASUS"
        elif _has_any(servers, ["netgear"]): brand = "Netgear"
        elif _has_any(servers, ["tp-link"]): brand = "TP-Link"
        elif _has_any(servers, ["unifi", "ubiquiti"]): brand = "Ubiquiti"
        return _result("router", brand, "Router", "high")

    # ---- iPhone / iPad (definitive mDNS signal) ----
    if "apple-mobdev2-tcp" in services:
        if "ipad" in all_hn:
            return _result("tablet", "Apple", "iPad", "high")
        if "iphone" in all_hn:
            return _result("phone", "Apple", "iPhone", "high")
        return _result("phone", "Apple", "iOS device", "high")

    # ---- Mac (AirPlay receiver + companion-link / workstation, or 62078 + airplay) ----
    is_mac_signal = (
        "workstation-tcp" in services
        or ("airplay-tcp" in services and "companion-link-tcp" in services)
        or ("raop-tcp" in services and "airplay-tcp" in services)
    )
    if is_mac_signal:
        if "macbook" in all_hn or "imac" in all_hn or "mac-mini" in all_hn or "mac mini" in all_hn:
            return _result("computer", "Apple", "Mac", "high")
        # AirPlay + companion-link + raop without "homepod"/"apple tv" hostname → likely a Mac
        if "homepod" not in all_hn and "apple tv" not in all_hn and "appletv" not in all_hn:
            return _result("computer", "Apple", "Mac", "medium")

    # ---- Apple TV / HomePod (AirPlay receivers) ----
    if "airplay-tcp" in services or 7000 in ports:
        if "apple tv" in all_hn or "appletv" in all_hn:
            return _result("tv", "Apple", "Apple TV", "high")
        if "homepod" in all_hn:
            return _result("speaker", "Apple", "HomePod", "high")
        if "raop-tcp" in services:
            return _result("speaker", "Apple", "AirPlay receiver", "medium")
        return _result("tv", "Apple", "AirPlay device", "medium")

    # ---- iPhone via lockdownd-only signal (no mDNS — quiet phone) ----
    if 62078 in ports:
        return _result("phone", "Apple", "iOS device", "medium")

    # ---- Chromecast / Google ----
    if "googlecast-tcp" in services or 8009 in ports or 8008 in ports:
        if "chromecast" in all_hn:
            return _result("tv", "Google", "Chromecast", "high")
        if "google home" in all_hn or "nest" in all_hn:
            return _result("speaker", "Google", "Google Home/Nest", "high")
        return _result("tv", "Google", "Cast device", "medium")

    # ---- Roku ----
    if _has_any(servers, ["roku"]) or 8060 in ports:
        return _result("tv", "Roku", "Roku", "high")

    # ---- Sonos ----
    if "sonos-tcp" in services or _has_any(servers, ["sonos"]):
        return _result("speaker", "Sonos", "Sonos", "high")

    # ---- Spotify Connect (generic music endpoint) ----
    if "spotify-connect-tcp" in services:
        return _result("speaker", None, "Music streamer", "low")

    # ---- Samsung TV ----
    if _has_any(servers, ["samsung"]) and (_has_any(servers, ["tv", "smarttv"]) or "tv" in all_hn):
        return _result("tv", "Samsung", "Samsung TV", "high")

    # ---- LG TV ----
    if _has_any(servers, ["webos", "lg "]):
        return _result("tv", "LG", "LG webOS TV", "high")

    # ---- Fire TV ----
    if "amzn-wplay-tcp" in services or _has_any(servers, ["amazon"]):
        return _result("tv", "Amazon", "Fire TV / Echo", "medium")

    # ---- HomeKit-only (smart home accessory) ----
    if ("hap-tcp" in services or "homekit-tcp" in services) and not services & {"airplay-tcp", "raop-tcp"}:
        return _result("iot", None, "HomeKit accessory", "high")

    # ---- Philips Hue ----
    if "hue-tcp" in services or _has_any(servers, ["philips hue"]):
        return _result("iot", "Philips", "Hue Bridge", "high")

    # ---- Printer ----
    if services & {"printer-tcp", "ipp-tcp", "ipps-tcp", "pdl-datastream-tcp"} or 9100 in ports:
        if "hp" in (vendor or "").lower(): brand = "HP"
        elif "epson" in (vendor or "").lower(): brand = "Epson"
        elif "canon" in (vendor or "").lower(): brand = "Canon"
        elif "brother" in (vendor or "").lower(): brand = "Brother"
        else: brand = vendor
        return _result("printer", brand, "Printer", "high")

    # ---- NAS ----
    if _has_any(servers, ["synology"]):
        return _result("nas", "Synology", "Synology NAS", "high")
    if _has_any(servers, ["qnap"]):
        return _result("nas", "QNAP", "QNAP NAS", "high")

    # ---- Computer (workstation / SMB / SSH) ----
    if "workstation-tcp" in services:
        if "macbook" in all_hn or "imac" in all_hn:
            return _result("computer", "Apple", "Mac", "high")
        return _result("computer", vendor, "Computer", "medium")
    if 22 in ports or 548 in ports:
        return _result("computer", vendor, "Computer", "medium")
    if 445 in ports or "smb-tcp" in services:
        return _result("computer", vendor, "Computer or NAS", "low")

    # ---- IoT / MQTT ----
    if 1883 in ports:
        return _result("iot", vendor, "IoT device", "medium")

    # ---- HTTP title hints (for everything that didn't match above) ----
    titles_blob = " ".join(signals.http_titles).lower()
    if titles_blob:
        if any(s in titles_blob for s in ["synology", "diskstation", "dsm "]):
            return _result("nas", "Synology", "Synology NAS", "high")
        if any(s in titles_blob for s in ["qnap"]):
            return _result("nas", "QNAP", "QNAP NAS", "high")
        if "tp-link" in titles_blob or "tplink" in titles_blob:
            return _result("router", "TP-Link", "TP-Link router/AP", "high")
        if any(s in titles_blob for s in ["asus router", "rt-ac", "rt-ax"]):
            return _result("router", "ASUS", "ASUS router", "high")
        if any(s in titles_blob for s in ["netgear", "nighthawk", "orbi"]):
            return _result("router", "Netgear", "Netgear router/AP", "high")
        if "linksys" in titles_blob:
            return _result("router", "Linksys", "Linksys router", "high")
        if any(s in titles_blob for s in ["unifi", "ubiquiti", "udm"]):
            return _result("router", "Ubiquiti", "UniFi device", "high")
        if "eero" in titles_blob:
            return _result("router", "eero", "eero mesh node", "high")
        if any(s in titles_blob for s in ["hikvision", "dahua", "nvr ", "dvr ", "ip camera", "网络摄像机"]):
            return _result("iot", None, "IP camera / NVR", "high")
        if any(s in titles_blob for s in ["hp laserjet", "hp officejet", "hp ", "officejet", "laserjet"]):
            return _result("printer", "HP", "HP printer", "high")
        if any(s in titles_blob for s in ["brother ", "brother-"]):
            return _result("printer", "Brother", "Brother printer", "high")
        if "epson" in titles_blob:
            return _result("printer", "Epson", "Epson printer", "high")
        if any(s in titles_blob for s in ["canon ", "pixma"]):
            return _result("printer", "Canon", "Canon printer", "high")
        if "philips hue" in titles_blob or "hue bridge" in titles_blob:
            return _result("iot", "Philips", "Hue Bridge", "high")
        # Generic web-accessible device — show the title so the user can see what it is
        sample = next(iter(signals.http_titles))
        return _result("unknown", vendor, sample[:48], "medium")

    # ---- Generic UPnP fallback ----
    if servers:
        srv = next(iter(servers))
        return _result("unknown", vendor, srv[:48], "low")

    return _result("unknown", vendor, None, "low")


def _result(device_type: str, brand: str | None, model: str | None, confidence: str) -> dict:
    return {
        "device_type": device_type,
        "brand": brand,
        "model": model,
        "confidence": confidence,
    }


# ---------- Gateway detection ----------

def detect_gateway() -> str | None:
    """Get the default route's gateway IP (macOS)."""
    try:
        out = subprocess.check_output(["/sbin/route", "-n", "get", "default"], text=True, timeout=2)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("gateway:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None

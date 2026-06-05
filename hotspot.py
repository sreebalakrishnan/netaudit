"""Personal-hotspot detection — is the current network the user's own phone?

netaudit's safety heuristics are tuned for public/unknown café Wi-Fi. A personal
hotspot (iOS / Android tethering) is the *safest* network you can be on — your own
device, WPA2, only your hardware on it — yet several public-Wi-Fi rules false-fire
on it (phones randomize MACs, so the rogue-AP check flags the gateway). So at the
start of the safety eval we ask "is this a personal hotspot?" and, when confident,
treat it as a trusted network instead of running those rules.

Pure standard library. Relies only on the macOS BSD tools already used elsewhere in
the app (route, ifconfig, arp, system_profiler). Absolute binary paths per the
project convention — bare names fail in the py2app subprocess env on Apple Silicon.
"""
from __future__ import annotations

import ipaddress
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum

ROUTE = "/sbin/route"
IFCONFIG = "/sbin/ifconfig"
ARP = "/usr/sbin/arp"
SYSTEM_PROFILER = "/usr/sbin/system_profiler"


class HotspotKind(str, Enum):
    APPLE = "apple_personal_hotspot"
    ANDROID = "android_tethering"
    GENERIC = "generic_phone_hotspot"
    NONE = "not_a_hotspot"


# iOS Personal Hotspot ALWAYS hands out 172.20.10.0/28 with the phone at .1.
# This is the single strongest fingerprint we have.
APPLE_HOTSPOT_GW = ipaddress.ip_address("172.20.10.1")

# Common Android / phone tethering gateways (varies by vendor & OS version).
ANDROID_HOTSPOT_GWS = {
    ipaddress.ip_address("192.168.43.1"),   # classic AOSP tethering
    ipaddress.ip_address("192.168.44.1"),
    ipaddress.ip_address("192.168.137.1"),  # also Windows ICS
}

# Tiny curated set of MAC OUIs that strongly suggest a phone is the router.
# Not exhaustive — these are high-signal *confirmations*, not the primary check.
PHONE_OUIS = {
    # Apple
    "00:1c:b3", "3c:15:c2", "f0:18:98", "a4:83:e7", "dc:a9:04",
    # Samsung
    "00:12:fb", "5c:0a:5b", "8c:77:12",
    # Google
    "94:eb:cd", "f8:0f:f9",
}

IS_HOTSPOT_THRESHOLD = 0.6
IS_TRUSTED_THRESHOLD = 0.8


@dataclass
class HotspotResult:
    kind: HotspotKind
    confidence: float          # 0.0 – 1.0
    interface: str | None = None
    gateway_ip: str | None = None
    gateway_mac: str | None = None
    ssid: str | None = None
    evidence: list[str] = field(default_factory=list)

    @property
    def is_hotspot(self) -> bool:
        return self.kind is not HotspotKind.NONE and self.confidence >= IS_HOTSPOT_THRESHOLD

    @property
    def is_trusted(self) -> bool:
        """A confident personal hotspot is your own device → trust it."""
        return self.is_hotspot and self.confidence >= IS_TRUSTED_THRESHOLD

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "confidence": self.confidence,
            "is_hotspot": self.is_hotspot,
            "is_trusted": self.is_trusted,
            "interface": self.interface,
            "gateway_ip": self.gateway_ip,
            "gateway_mac": self.gateway_mac,
            "ssid": self.ssid,
            "evidence": self.evidence,
        }


def _run(cmd: list[str]) -> str:
    """Run a BSD tool and return stdout (empty string on any failure)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=4).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def _default_route() -> tuple[str | None, str | None]:
    """Return (gateway_ip, interface) for the default route."""
    out = _run([ROUTE, "-n", "get", "default"])
    gw = iface = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("gateway:"):
            gw = line.split(":", 1)[1].strip()
        elif line.startswith("interface:"):
            iface = line.split(":", 1)[1].strip()
    return gw, iface


def _netmask(iface: str) -> str | None:
    """Return the interface's IPv4 netmask in dotted form (e.g. 255.255.255.240)."""
    out = _run([IFCONFIG, iface])
    m = re.search(r"netmask 0x([0-9a-fA-F]{8})", out)
    if not m:
        return None
    return str(ipaddress.ip_address(int(m.group(1), 16)))


def _gateway_mac(gw_ip: str) -> str | None:
    out = _run([ARP, "-n", gw_ip])
    m = re.search(r"([0-9a-fA-F]{1,2}(?::[0-9a-fA-F]{1,2}){5})", out)
    if not m:
        return None
    return ":".join(p.zfill(2).lower() for p in m.group(1).split(":"))


def _current_ssid() -> str | None:
    # `airport -I` was removed in recent macOS; system_profiler still reports the
    # current SSID. May need Location permission on Sonoma+ — treat as best-effort.
    out = _run([SYSTEM_PROFILER, "SPAirPortDataType"])
    m = re.search(r"Current Network Information:\s*\n\s*(.+?):", out)
    return m.group(1).strip() if m else None


def detect_hotspot() -> HotspotResult:
    """Fingerprint the current default network as a personal hotspot (or not)."""
    gw_ip, iface = _default_route()
    if not gw_ip or not iface:
        return HotspotResult(HotspotKind.NONE, 0.0, evidence=["no default route"])

    try:
        gw = ipaddress.ip_address(gw_ip)
    except ValueError:
        return HotspotResult(HotspotKind.NONE, 0.0, gateway_ip=gw_ip, interface=iface,
                             evidence=[f"unparseable gateway {gw_ip!r}"])

    mask = _netmask(iface)
    mac = _gateway_mac(gw_ip)
    ssid = _current_ssid()
    ev: list[str] = []
    score = 0.0
    kind = HotspotKind.NONE

    # --- Apple Personal Hotspot: strongest single fingerprint ---
    if gw == APPLE_HOTSPOT_GW:
        kind = HotspotKind.APPLE
        score = 0.90
        ev.append(f"gateway {gw_ip} is the fixed iOS Personal Hotspot address")
        if mask == "255.255.255.240":
            score = 0.97
            ev.append("subnet is /28 (172.20.10.0/28) — unique to iOS tethering")

    # --- Android / phone tethering ---
    elif gw in ANDROID_HOTSPOT_GWS:
        kind = HotspotKind.ANDROID
        score = 0.85
        ev.append(f"gateway {gw_ip} matches a common phone-tethering range")

    # --- OUI confirmation: gateway MAC belongs to a phone vendor ---
    if mac and mac[:8] in PHONE_OUIS:
        ev.append(f"gateway MAC {mac} OUI belongs to a phone vendor")
        if kind is HotspotKind.NONE:
            kind, score = HotspotKind.GENERIC, max(score, 0.70)
        else:
            score = min(1.0, score + 0.03)

    # --- SSID hint (weak, best-effort) ---
    if ssid and re.search(r"\b(iphone|ipad|androidap|hotspot)\b", ssid, re.I):
        ev.append(f"SSID '{ssid}' looks like a device name")
        score = min(1.0, score + 0.05)
        if kind is HotspotKind.NONE:
            kind, score = HotspotKind.GENERIC, max(score, 0.55)

    return HotspotResult(
        kind=kind,
        confidence=round(score, 2),
        interface=iface,
        gateway_ip=gw_ip,
        gateway_mac=mac,
        ssid=ssid,
        evidence=ev,
    )


if __name__ == "__main__":
    r = detect_hotspot()
    print(f"kind:       {r.kind.value}")
    print(f"confidence: {r.confidence}")
    print(f"is_hotspot: {r.is_hotspot}")
    print(f"is_trusted: {r.is_trusted}")
    print(f"interface:  {r.interface}")
    print(f"gateway:    {r.gateway_ip}  mac={r.gateway_mac}")
    print(f"ssid:       {r.ssid}")
    print("evidence:")
    for e in r.evidence:
        print(f"  - {e}")

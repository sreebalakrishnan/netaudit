"""Unit tests for the personal-hotspot detector.

Mocks the BSD-tool output (route / ifconfig / arp / system_profiler) so the
detector's scoring is exercised without touching the real network. Because the
module uses absolute binary paths (project convention), the fake keys off the
command basename rather than the full path.

Run: python -m pytest test_hotspot.py -v   (or: python test_hotspot.py)
"""
import hotspot


# --- Case A: iOS Personal Hotspot — gateway 172.20.10.1, /28, Apple OUI ---

ROUTE_HOTSPOT = """\
   route to: default
    gateway: 172.20.10.1
  interface: en0
"""

IFCONFIG_HOTSPOT = """\
en0: flags=8863 mtu 1500
\tether f0:18:98:3a:1c:7e
\tinet 172.20.10.5 netmask 0xfffffff0 broadcast 172.20.10.15
\tstatus: active
"""

ARP_HOTSPOT = "? (172.20.10.1) at 3c:15:c2:aa:b9:04 on en0 ifscope [ethernet]\n"

SPAIRPORT_HOTSPOT = """\
            Current Network Information:
              iPhone 17 max:
                PHY Mode: 802.11ax
                Security: WPA2 Personal
"""

# --- Case B: normal home Wi-Fi — gateway 192.168.1.1, /24, Netgear OUI ---

ROUTE_HOME = """\
   route to: default
    gateway: 192.168.1.1
  interface: en0
"""

IFCONFIG_HOME = """\
en0: flags=8863 mtu 1500
\tether f0:18:98:3a:1c:7e
\tinet 192.168.1.42 netmask 0xffffff00 broadcast 192.168.1.255
\tstatus: active
"""

ARP_HOME = "? (192.168.1.1) at 9c:3d:cf:11:22:33 on en0 ifscope [ethernet]\n"


def _fake_run(table):
    """Build a _run replacement that keys mock output by command basename."""
    def run(cmd):
        base = cmd[0].rsplit("/", 1)[-1]
        if base == "route":
            return table["route"]
        if base == "ifconfig":
            return table["ifconfig"]
        if base == "arp":
            return table["arp"]
        if base == "system_profiler":
            return table.get("spairport", "")
        return ""
    return run


def test_ios_personal_hotspot_is_trusted(monkeypatch):
    monkeypatch.setattr(hotspot, "_run", _fake_run({
        "route": ROUTE_HOTSPOT,
        "ifconfig": IFCONFIG_HOTSPOT,
        "arp": ARP_HOTSPOT,
        "spairport": SPAIRPORT_HOTSPOT,
    }))
    r = hotspot.detect_hotspot()
    assert r.kind is hotspot.HotspotKind.APPLE
    assert r.is_trusted is True
    assert r.confidence >= 0.95
    assert r.gateway_ip == "172.20.10.1"
    assert r.gateway_mac == "3c:15:c2:aa:b9:04"
    assert any("/28" in e for e in r.evidence)


def test_ios_hotspot_without_arp_or_ssid(monkeypatch):
    # Subnet + gateway alone must already clear the trust bar (0.97 >= 0.8).
    monkeypatch.setattr(hotspot, "_run", _fake_run({
        "route": ROUTE_HOTSPOT,
        "ifconfig": IFCONFIG_HOTSPOT,
        "arp": "",
        "spairport": "",
    }))
    r = hotspot.detect_hotspot()
    assert r.kind is hotspot.HotspotKind.APPLE
    assert r.is_trusted is True
    assert r.gateway_mac is None


def test_home_wifi_is_not_a_hotspot(monkeypatch):
    monkeypatch.setattr(hotspot, "_run", _fake_run({
        "route": ROUTE_HOME,
        "ifconfig": IFCONFIG_HOME,
        "arp": ARP_HOME,
    }))
    r = hotspot.detect_hotspot()
    assert r.kind is hotspot.HotspotKind.NONE
    assert r.is_hotspot is False
    assert r.is_trusted is False


def test_no_default_route(monkeypatch):
    monkeypatch.setattr(hotspot, "_run", _fake_run({
        "route": "", "ifconfig": "", "arp": "",
    }))
    r = hotspot.detect_hotspot()
    assert r.is_hotspot is False
    assert "no default route" in r.evidence


def test_android_tethering_is_hotspot(monkeypatch):
    monkeypatch.setattr(hotspot, "_run", _fake_run({
        "route": "    gateway: 192.168.43.1\n  interface: en0\n",
        "ifconfig": "en0: flags=8863\n\tinet 192.168.43.50 netmask 0xffffff00\n",
        "arp": "",
    }))
    r = hotspot.detect_hotspot()
    assert r.kind is hotspot.HotspotKind.ANDROID
    assert r.is_hotspot is True


if __name__ == "__main__":
    import subprocess
    import sys
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))

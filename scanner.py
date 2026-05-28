from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

import psutil

import fingerprint
from fingerprint import Signals

try:
    from mac_vendor_lookup import MacLookup
    _mac_lookup = MacLookup()
except Exception:
    _mac_lookup = None


def detect_subnet() -> str:
    """Pick the first private IPv4 interface that's up and return its /24."""
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    for iface, snics in addrs.items():
        if iface.startswith("lo") or not stats.get(iface) or not stats[iface].isup:
            continue
        for snic in snics:
            if snic.family != socket.AF_INET:
                continue
            ip = ipaddress.IPv4Address(snic.address)
            if not ip.is_private or ip.is_loopback or ip.is_link_local:
                continue
            netmask = snic.netmask or "255.255.255.0"
            net = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
            if net.prefixlen < 24:
                net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
            return str(net)
    raise RuntimeError("No suitable private IPv4 interface found")


def resolve_subnet(subnet: str) -> ipaddress.IPv4Network:
    if subnet == "auto":
        subnet = detect_subnet()
    return ipaddress.IPv4Network(subnet, strict=False)


PING = "/sbin/ping"
ARP = "/usr/sbin/arp"


def _ping(ip: str) -> bool:
    try:
        r = subprocess.run(
            [PING, "-c", "1", "-W", "300", ip],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
        return r.returncode == 0
    except Exception:
        return False


def ping_sweep(network: ipaddress.IPv4Network, workers: int = 64) -> set[str]:
    hosts = [str(h) for h in network.hosts()]
    alive: set[str] = set()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for ip, ok in zip(hosts, ex.map(_ping, hosts)):
            if ok:
                alive.add(ip)
    return alive


_ARP_RE = re.compile(r"\((?P<ip>\d+\.\d+\.\d+\.\d+)\) at (?P<mac>[0-9a-fA-F:]{11,17})")


def read_arp_table() -> dict[str, str]:
    try:
        out = subprocess.check_output([ARP, "-a"], text=True, timeout=5)
    except Exception:
        return {}
    table: dict[str, str] = {}
    for line in out.splitlines():
        m = _ARP_RE.search(line)
        if not m:
            continue
        mac = m.group("mac")
        if mac in ("(incomplete)", "ff:ff:ff:ff:ff:ff"):
            continue
        parts = [p.zfill(2) for p in mac.split(":")]
        table[m.group("ip")] = ":".join(parts).lower()
    return table


def resolve_hostname(ip: str) -> str | None:
    try:
        # Short timeout — many devices won't reverse-resolve
        socket.setdefaulttimeout(2.0)
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None


def vendor_for_mac(mac: str | None) -> str | None:
    if not mac or _mac_lookup is None:
        return None
    try:
        return _mac_lookup.lookup(mac)
    except Exception:
        return None


def _merge_signals(*sources: dict[str, Signals]) -> dict[str, Signals]:
    merged: dict[str, Signals] = {}
    for src in sources:
        for ip, sig in src.items():
            cur = merged.setdefault(ip, Signals())
            cur.services |= sig.services
            cur.mdns_hostnames |= sig.mdns_hostnames
            cur.ssdp_servers |= sig.ssdp_servers
            cur.open_ports |= sig.open_ports
    return merged


def scan(subnet: str = "auto") -> tuple[str, list[dict]]:
    """Run a full scan with fingerprinting. Returns (subnet, devices)."""
    network = resolve_subnet(subnet)
    gateway = fingerprint.detect_gateway()

    # Run mDNS + SSDP discovery in parallel with the ping sweep
    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_mdns = ex.submit(fingerprint.discover_mdns, 5.0)
        fut_ssdp = ex.submit(fingerprint.discover_ssdp, 3.0)
        fut_alive = ex.submit(ping_sweep, network)
        mdns_sig = fut_mdns.result()
        ssdp_sig = fut_ssdp.result()
        alive = fut_alive.result()

    arp = read_arp_table()
    ips = (alive | set(arp.keys()) | set(mdns_sig.keys()) | set(ssdp_sig.keys()))
    ips = {ip for ip in ips if ipaddress.IPv4Address(ip) in network}

    # Hostnames + per-host port probes in parallel
    with ThreadPoolExecutor(max_workers=16) as ex:
        hostnames = dict(zip(ips, ex.map(resolve_hostname, ips)))
        port_results = dict(zip(ips, ex.map(fingerprint.probe_ports, ips)))

    # Build port signals into the merge
    port_sig = {ip: Signals(open_ports=ports) for ip, ports in port_results.items()}
    signals = _merge_signals(mdns_sig, ssdp_sig, port_sig)

    devices: list[dict] = []
    for ip in sorted(ips, key=lambda s: tuple(int(o) for o in s.split("."))):
        mac = arp.get(ip)
        sig = signals.get(ip, Signals())
        info = fingerprint.classify(
            ip=ip, mac=mac, hostname=hostnames.get(ip),
            vendor=vendor_for_mac(mac), signals=sig, gateway_ip=gateway,
        )
        devices.append({
            "ip": ip,
            "mac": mac,
            "hostname": hostnames.get(ip) or (next(iter(sig.mdns_hostnames), None)),
            "vendor": vendor_for_mac(mac),
            "device_type": info["device_type"],
            "brand": info["brand"],
            "model": info["model"],
            "confidence": info["confidence"],
            "services": sorted(sig.services),
            "open_ports": sorted(sig.open_ports),
            "ssdp": sorted(sig.ssdp_servers)[:3],
        })
    return str(network), devices

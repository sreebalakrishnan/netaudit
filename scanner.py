import ipaddress
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

import psutil

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
            # Cap to /24 to keep scans fast
            if net.prefixlen < 24:
                net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
            return str(net)
    raise RuntimeError("No suitable private IPv4 interface found")


def resolve_subnet(subnet: str) -> ipaddress.IPv4Network:
    if subnet == "auto":
        subnet = detect_subnet()
    return ipaddress.IPv4Network(subnet, strict=False)


def _ping(ip: str) -> bool:
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "300", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
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


_ARP_RE = re.compile(
    r"\((?P<ip>\d+\.\d+\.\d+\.\d+)\) at (?P<mac>[0-9a-fA-F:]{11,17})"
)


def read_arp_table() -> dict[str, str]:
    """Return {ip: mac} from `arp -a` output."""
    try:
        out = subprocess.check_output(["arp", "-a"], text=True, timeout=5)
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
        # Normalize MAC: pad single-digit octets, lowercase
        parts = [p.zfill(2) for p in mac.split(":")]
        table[m.group("ip")] = ":".join(parts).lower()
    return table


def resolve_hostname(ip: str) -> str | None:
    try:
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


def scan(subnet: str = "auto") -> tuple[str, list[dict]]:
    """Run a full scan. Returns (resolved subnet string, device list)."""
    network = resolve_subnet(subnet)
    alive = ping_sweep(network)
    arp = read_arp_table()

    ips = alive | set(arp.keys())
    devices: list[dict] = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        hostnames = dict(zip(ips, ex.map(resolve_hostname, ips)))

    for ip in sorted(ips, key=lambda s: tuple(int(o) for o in s.split("."))):
        if ipaddress.IPv4Address(ip) not in network:
            continue
        mac = arp.get(ip)
        devices.append({
            "ip": ip,
            "mac": mac,
            "hostname": hostnames.get(ip),
            "vendor": vendor_for_mac(mac),
        })
    return str(network), devices

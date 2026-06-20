"""Host network diagnostics (Diagnostics page).

Reports the host device's primary network connection: IP, up/down status, and — depending on the
link type — the Wi-Fi SSID + signal, or the Ethernet interface name + link speed. Linux-focused
(the deploy target is a Raspberry Pi / Ubuntu, CLAUDE.md): it reads `/proc/net/route`,
`/proc/net/wireless` and `/sys/class/net/*` (no extra dependencies) and shells out to `iwgetid`
only for the SSID. **Best-effort** — every probe degrades to `None` so a missing tool or a
non-Linux host can never break the diagnostics endpoint.

The low-level probes are injectable so the composition is unit-testable without touching the host.
"""

from __future__ import annotations

import os
import socket
import subprocess


def _primary_ip() -> str | None:
    """The source IP of the default route (no packets are sent — UDP connect just selects a route)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def _primary_iface() -> str | None:
    """The default-route interface name from /proc/net/route (Destination 00000000)."""
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "00000000":
                    return parts[0]
    except OSError:
        return None
    return None


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _is_wifi(iface: str) -> bool:
    return os.path.isdir(f"/sys/class/net/{iface}/wireless")


def _ssid(iface: str) -> str | None:
    try:
        out = subprocess.run(["iwgetid", iface, "-r"], capture_output=True, text=True, timeout=2)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _wifi_signal(iface: str) -> tuple[int | None, int | None]:
    """(link-quality, signal-level dBm) from /proc/net/wireless, e.g. `wlan0: 0000 70. -45. ...`."""
    try:
        with open("/proc/net/wireless") as f:
            for line in f:
                if line.strip().startswith(iface + ":"):
                    fields = line.split()
                    quality = int(float(fields[2].rstrip("."))) if len(fields) > 2 else None
                    level = int(float(fields[3].rstrip("."))) if len(fields) > 3 else None
                    return quality, level
    except (OSError, ValueError, IndexError):
        pass
    return None, None


def _pct_from_dbm(dbm: int | None) -> int | None:
    """A rough 0–100 % bar from a dBm level (≈ −100 dBm = 0 %, −50 dBm = 100 %)."""
    if dbm is None:
        return None
    return max(0, min(100, 2 * (dbm + 100)))


def host_network(
    *,
    primary_iface=_primary_iface,
    primary_ip=_primary_ip,
    is_wifi=_is_wifi,
    operstate=lambda i: _read(f"/sys/class/net/{i}/operstate"),
    eth_speed=lambda i: _read(f"/sys/class/net/{i}/speed"),
    ssid=_ssid,
    wifi_signal=_wifi_signal,
) -> dict:
    """Snapshot of the host's primary network link. Fields are `None` when unavailable."""
    iface = primary_iface()
    ip = primary_ip()
    result: dict = {
        "interface": iface,
        "ip": ip,
        "type": "unknown",
        "status": None,
        "wifi": None,
        "ethernet": None,
    }
    if not iface:
        result["status"] = "connected" if ip else "disconnected"
        return result

    result["status"] = operstate(iface) or ("connected" if ip else None)
    if is_wifi(iface):
        result["type"] = "wifi"
        quality, dbm = wifi_signal(iface)
        result["wifi"] = {
            "ssid": ssid(iface),
            "signal_dbm": dbm,
            "signal_pct": _pct_from_dbm(dbm),
            "link_quality": quality,
        }
    else:
        result["type"] = "ethernet"
        speed = eth_speed(iface)
        mbps = int(speed) if speed and speed.lstrip("-").isdigit() and int(speed) >= 0 else None
        result["ethernet"] = {"name": iface, "link_speed_mbps": mbps}
    return result

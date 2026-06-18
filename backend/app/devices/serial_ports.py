"""Enumerate the host's serial / tty devices for the device-setup UI.

The Settings → Add device form offers a dropdown of the RS485 adapters actually
present (`/dev/ttyUSB*`, `/dev/ttyAMA*`, …) instead of a free-text box, so the user
picks a real port rather than guessing. Read-only discovery — knows no brand, touches
no register. pyserial ships as a pymodbus dependency (requirements.txt); if it is ever
absent we degrade to an empty list rather than failing the page.
"""

from __future__ import annotations


def list_serial_ports() -> list[dict]:
    """Available serial ports as ``{device, description, hwid}`` dicts, sorted by
    device path. Empty list when pyserial is missing or no ports are present."""
    try:
        from serial.tools import list_ports
    except ImportError:  # pragma: no cover - pyserial is a declared dependency
        return []

    def _clean(value: str | None) -> str:
        # pyserial uses the literal "n/a" for unknown description/hwid; show nothing instead.
        text = (value or "").strip()
        return "" if text.lower() == "n/a" else text

    ports = [
        {
            "device": p.device,
            "description": _clean(p.description),
            "hwid": _clean(p.hwid),
        }
        for p in list_ports.comports()
    ]
    return sorted(ports, key=lambda p: p["device"])

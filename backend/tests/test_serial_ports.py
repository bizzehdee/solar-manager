"""Serial-port enumeration for the device-setup UI."""

from __future__ import annotations

import sys
import types

from app.devices import serial_ports


class _FakePort:
    def __init__(self, device, description, hwid):
        self.device = device
        self.description = description
        self.hwid = hwid


def test_list_serial_ports_sorts_and_cleans_na(monkeypatch):
    fake = [
        _FakePort("/dev/ttyUSB1", "n/a", "n/a"),
        _FakePort("/dev/ttyUSB0", "USB Serial ", " VID:PID=1A86 "),
    ]
    mod = types.ModuleType("serial.tools.list_ports")
    mod.comports = lambda: fake
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", mod)

    ports = serial_ports.list_serial_ports()
    assert [p["device"] for p in ports] == ["/dev/ttyUSB0", "/dev/ttyUSB1"]
    # "n/a" placeholders become empty; real values are stripped.
    assert ports[0] == {"device": "/dev/ttyUSB0", "description": "USB Serial", "hwid": "VID:PID=1A86"}
    assert ports[1]["description"] == "" and ports[1]["hwid"] == ""

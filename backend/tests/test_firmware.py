"""Firmware-pin verification (plan.md §4, Decision #1; task T032).

Pure comparison (`firmware_mismatches`) is unit-tested hard; the connect-time
`verify_firmware` flow is tested against a fake transport that returns scripted
identity registers — warn on mismatch, never raise.
"""

from __future__ import annotations

import logging

import pytest

from app.devices.base import Device, TransportError, system_clock
from app.devices.dummy import DummyProfile, NullTransport
from app.devices.firmware import verify_firmware
from app.devices.yaml_profile import ModbusYamlProfile


def _profile() -> ModbusYamlProfile:
    return ModbusYamlProfile.from_name("sunsynk-8k-sg05lp1")


# --- pure comparison --------------------------------------------------------------
def test_pinned_firmware_from_profile():
    assert _profile().pinned_firmware() == {"protocol": "2.1", "mcu": "5386", "comm": "e43d"}


def test_no_mismatch_when_observed_matches():
    assert _profile().firmware_mismatches({"protocol": "2.1"}) == []


def test_mismatch_reported_for_observed_protocol():
    out = _profile().firmware_mismatches({"protocol": "9.9"})
    assert len(out) == 1 and "protocol" in out[0]


def test_unobservable_pins_are_skipped_not_warned():
    # mcu/comm have no register address in the map, so an empty identity yields no
    # mismatch — we never warn about something we couldn't read.
    assert _profile().firmware_mismatches({}) == []


def test_comparison_is_string_normalized():
    # An int register decoding to 21 / "21" / 2.1 normalizes equal to a "2.1"/"21" pin.
    p = ModbusYamlProfile({"firmware": {"protocol": "21"}})
    assert p.firmware_mismatches({"protocol": 21}) == []
    assert p.firmware_mismatches({"protocol": 21.0}) == []


def test_unpinned_profile_has_no_mismatches():
    assert ModbusYamlProfile({}).pinned_firmware() is None
    assert ModbusYamlProfile({}).firmware_mismatches({"protocol": "x"}) == []


# --- connect-time flow ------------------------------------------------------------
class FakeTransport:
    """Returns scripted register values; optionally raises to simulate a bad bus."""

    def __init__(self, values=None, *, raise_on_read=False):
        self._values = values or {}
        self._raise = raise_on_read

    async def connect(self):  # pragma: no cover - unused here
        return None

    async def read_registers(self, start, count, table="holding"):
        if self._raise:
            raise TransportError("bus down")
        return [self._values.get(start + i, 0) for i in range(count)]

    async def write_registers(self, start, values):  # pragma: no cover
        return None

    async def close(self):  # pragma: no cover
        return None


def _device(transport, profile=None) -> Device:
    return Device("sunsynk", transport, profile or _profile(), clock=system_clock)


async def test_dummy_profile_is_skipped():
    dev = Device("dummy", NullTransport(), DummyProfile(), clock=system_clock)
    assert await verify_firmware(dev) == []


async def test_matching_firmware_no_warning(caplog):
    # info.protocol is addr 2 (u16); device reports 2 -> normalizes to the "2.1"? No:
    # "2" != "2.1", so to MATCH we pin a profile whose protocol register reads back equal.
    profile = ModbusYamlProfile(
        {"info": {"protocol": {"addr": 2, "type": "u16"}}, "firmware": {"protocol": "21"}}
    )
    dev = _device(FakeTransport({2: 21}), profile)
    with caplog.at_level(logging.WARNING):
        assert await verify_firmware(dev) == []
    assert "firmware" not in caplog.text.lower()


async def test_mismatch_logs_warning(caplog):
    profile = ModbusYamlProfile(
        {"info": {"protocol": {"addr": 2, "type": "u16"}}, "firmware": {"protocol": "21"}}
    )
    dev = _device(FakeTransport({2: 99}), profile)
    with caplog.at_level(logging.WARNING):
        out = await verify_firmware(dev)
    assert out and "protocol" in out[0]
    assert "re-run regscan" in caplog.text


async def test_real_profile_protocol_register_matches_pin(caplog):
    # The real device reports protocol register [2] = 0x0201, which decodes to "2.1"
    # via version_be and matches the profile's firmware pin -> no warning.
    dev = _device(FakeTransport({2: 0x0201}))
    with caplog.at_level(logging.WARNING):
        assert await verify_firmware(dev) == []
    assert "firmware" not in caplog.text.lower()


async def test_real_profile_protocol_mismatch_warns(caplog):
    dev = _device(FakeTransport({2: 0x0303}))  # decodes to "3.3" != pinned "2.1"
    with caplog.at_level(logging.WARNING):
        out = await verify_firmware(dev)
    assert out and "protocol" in out[0]


async def test_transport_error_downgrades_to_warning(caplog):
    dev = _device(FakeTransport(raise_on_read=True))
    with caplog.at_level(logging.WARNING):
        assert await verify_firmware(dev) == []
    assert "could not read identity" in caplog.text.lower()

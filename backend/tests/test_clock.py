"""Inverter clock sync (plan.md §19 / T097): RTC decode, drift, gated correction."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.devices.base import Device, system_clock
from app.devices.dummy import DummyProfile, NullTransport
from app.devices.yaml_profile import ModbusYamlProfile
from app.main import create_app

_BASE = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def _client(*, control: bool) -> TestClient:
    settings = Settings(enable_control=control, poll_interval_s=60, db_path=":memory:", persist_interval_s=3600)
    return TestClient(create_app(settings=settings, clock=lambda: _BASE))


# --- dummy (synthesised, syncable in-memory) ------------------------------------
async def test_dummy_clock_drifts_then_syncs():
    dev = Device("dummy", NullTransport(), DummyProfile(clock=lambda: _BASE))
    assert dev.has_clock and dev.clock_syncable
    dt = await dev.read_clock()
    assert (dt.timestamp() - _BASE.timestamp()) == 95.0  # synthetic drift
    await dev.sync_clock(_BASE)
    dt2 = await dev.read_clock()
    assert (dt2.timestamp() - _BASE.timestamp()) == 0.0  # synced → no drift


# --- YAML profile RTC decode/encode (real, read-only until confirmed) -----------
def test_yaml_rtc_decode_and_encode_roundtrip():
    p = ModbusYamlProfile.from_name("sunsynk-8k-sg05lp1")
    assert p.clock_syncable is False  # RTC registers unconfirmed ⇒ read-only
    when = datetime(2026, 6, 21, 14, 5, 9)
    regs = p.encode_clock(when)
    assert p.read_clock(regs) == when           # round-trips through the packed registers
    assert p.read_clock({}) is None             # absent registers ⇒ no reading
    assert p.clock_addresses() == {22, 23, 24}


def test_yaml_rtc_rejects_garbage_registers():
    p = ModbusYamlProfile.from_name("sunsynk-8k-sg05lp1")
    assert p.read_clock({22: 0xFFFF, 23: 0xFFFF, 24: 0xFFFF}) is None  # invalid m/d/h → None


# --- API: drift always readable; sync gated by control + confirmed registers ----
def test_clock_api_shows_drift_and_gating():
    with _client(control=False) as client:
        body = client.get("/api/devices/dummy/clock").json()
        assert body["supported"] is True
        assert body["drift_s"] == 95.0
        assert body["syncable"] is False           # control off
        # Sync refused when control is disabled.
        assert client.post("/api/devices/dummy/clock/sync").status_code == 403


def test_clock_api_syncs_when_control_enabled():
    with _client(control=True) as client:
        assert client.get("/api/devices/dummy/clock").json()["syncable"] is True
        r = client.post("/api/devices/dummy/clock/sync")
        assert r.status_code == 200 and r.json()["ok"] is True
        assert r.json()["drift_s"] == 0.0
        assert client.get("/api/devices/dummy/clock").json()["drift_s"] == 0.0

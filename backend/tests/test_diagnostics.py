"""Diagnostics endpoint + Modbus comms stats (plan.md §19 / T092)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.devices.modbus_rtu import ModbusRtuConfig, ModbusRtuSource
from app.main import create_app
from app.storage.migrations import SCHEMA_VERSION

_BASE = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def _client() -> TestClient:
    return TestClient(create_app(settings=Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600),
                                 clock=lambda: _BASE))


def test_diagnostics_reports_build_db_and_devices():
    with _client() as client:
        d = client.get("/api/diagnostics").json()
        assert d["schema_version"] == SCHEMA_VERSION
        assert d["database"]["path"] == ":memory:" and d["database"]["size_bytes"] is None
        assert d["alerts"]["active_count"] == 0
        dummy = next(x for x in d["devices"] if x["device_id"] == "dummy")
        assert dummy["online"] is True
        assert dummy["comms"] is None  # the dummy moves no bytes
        # Inverter clock drift now travels in the per-device diagnostics snapshot (T097).
        assert dummy["clock"]["supported"] is True
        assert isinstance(dummy["clock"]["drift_s"], (int, float))
        assert dummy["clock"]["syncable"] is False  # control disabled by default


# --- Modbus transport comms stats -----------------------------------------------
class _Rsp:
    def __init__(self, regs):
        self.registers = regs

    def isError(self):
        return False


class _FakeClient:
    def __init__(self, fail_first: int = 0) -> None:
        self._fail_first = fail_first
        self.calls = 0

    async def connect(self):
        return True

    async def read_holding_registers(self, address, *, count, device_id):
        self.calls += 1
        if self.calls <= self._fail_first:
            raise OSError("bus error")
        return _Rsp([0] * count)

    def close(self):
        return None


async def _nosleep(_):
    return None


async def test_comms_stats_count_success_retry_and_failure():
    client = _FakeClient(fail_first=1)  # first attempt errors, retry succeeds
    cfg = ModbusRtuConfig(port="x", retries=3, backoff_s=0.0)
    src = ModbusRtuSource(cfg, client_factory=lambda c: client, sleep=_nosleep)
    await src.connect()
    await src.read_registers(0, 2)

    s = src.comms_stats()
    assert s["transactions"] == 1 and s["retries"] == 1 and s["failures"] == 0
    assert s["last_rtt_ms"] is not None and s["last_error"] is None


async def test_comms_stats_record_failure():
    client = _FakeClient(fail_first=99)  # always fails
    src = ModbusRtuSource(ModbusRtuConfig(port="x", retries=2, backoff_s=0.0),
                          client_factory=lambda c: client, sleep=_nosleep)
    await src.connect()
    with pytest.raises(Exception):
        await src.read_registers(0, 1)
    s = src.comms_stats()
    assert s["failures"] == 1 and s["last_error"] is not None

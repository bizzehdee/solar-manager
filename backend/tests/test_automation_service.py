"""Opt-in automation apply + scheduler (L03e-3): the engine's armed winners written through the
§12 control flow, exercised against the dummy (in-memory writes, no hardware).

Preview/decision logic is unit-tested in test_automation_rules.py; here we cover the wiring:
coalescing per slot, read-back + audit, failure handling, and the background scheduler loop."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app import control
from app.automation.service import AutomationService
from app.devices.base import Device, TransportError
from app.devices.dummy import DummyProfile, NullTransport

# 2026-06-20 is a Saturday, so a weekend day-of-week rule matches.
_SAT = datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)


class _Registry:
    def __init__(self, devices: list[Device]) -> None:
        self._d = {d.device_id: d for d in devices}

    @property
    def devices(self) -> list[Device]:
        return list(self._d.values())

    def get(self, device_id: str) -> Device | None:
        return self._d.get(device_id)


class _Poller:
    def __init__(self, snapshot: dict | None = None) -> None:
        self._snap = snapshot or {"devices": {}}

    def snapshot(self) -> dict:
        return self._snap


class _Config:
    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    async def get(self, key: str, default=None):
        return self._data.get(key, default)

    async def set(self, key: str, value) -> None:
        self._data[key] = value


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record(self, ts, device_id, section, changes, result, *, slot=None, source=""):
        self.records.append({"section": section, "slot": slot, "result": result,
                             "source": source, "changes": changes})


def _weekend_rule(*, fields: dict, enabled=True, action_enabled=True, slot=1) -> dict:
    return {
        "id": "weekend", "name": "Weekend top-up", "match": "all", "enabled": enabled,
        "conditions": [{"kind": "day_of_week", "params": {"days": [5, 6]}}],
        "actions": [{"target": {"section": "timer_slots", "field": f, "index": slot},
                     "value": v, "enabled": action_enabled} for f, v in fields.items()],
    }


def _service(rules: list[dict], *, devices=None, audit=None, apply_fn=None) -> AutomationService:
    device = devices if devices is not None else [Device("dummy", NullTransport(), DummyProfile())]
    return AutomationService(
        _Config({"automation_rules": rules}), _Poller(), _Registry(device),
        clock=lambda: _SAT, audit_repo=audit or _Audit(), interval_s=300.0, apply_fn=apply_fn,
    )


@pytest.mark.asyncio
async def test_apply_writes_armed_winner_and_reads_back():
    audit = _Audit()
    svc = _service([_weekend_rule(fields={"target_soc_pct": 80})], audit=audit)
    out = await svc.apply("dummy")

    assert out["device_id"] == "dummy" and out["failed"] == []
    assert len(out["applied"]) == 1
    applied = out["applied"][0]
    assert applied == {
        "section": "timer_slots", "index": 1, "ok": True,
        "changes": applied["changes"], "mismatches": [], "etag": applied["etag"],
    }
    assert applied["changes"]["target_soc_pct"]["new"] == 80

    # The write landed on the device (read-back), and the audit log captured it.
    settings = await svc._registry.get("dummy").read_settings()
    assert settings["timer_slots"][1]["target_soc_pct"] == 80
    assert audit.records[0]["result"] == "ok" and audit.records[0]["source"] == "automation"


@pytest.mark.asyncio
async def test_apply_coalesces_fields_in_one_slot_into_one_write():
    svc = _service([_weekend_rule(fields={"target_soc_pct": 75, "power_w": 6000})])
    out = await svc.apply("dummy")
    # Two fields, same slot ⇒ a single apply (one §12 slot write), both changes reported.
    assert len(out["applied"]) == 1
    changes = out["applied"][0]["changes"]
    assert changes["target_soc_pct"]["new"] == 75 and changes["power_w"]["new"] == 6000


@pytest.mark.asyncio
async def test_apply_skips_preview_only_rule():
    audit = _Audit()
    svc = _service([_weekend_rule(fields={"target_soc_pct": 80}, enabled=False)], audit=audit)
    out = await svc.apply("dummy")
    assert out["applied"] == [] and out["failed"] == [] and audit.records == []


@pytest.mark.asyncio
async def test_apply_records_and_continues_past_a_write_failure():
    async def boom(device, section, values, *, index=None):
        raise control.SettingsError("device said no")

    audit = _Audit()
    svc = _service([_weekend_rule(fields={"target_soc_pct": 80})], audit=audit, apply_fn=boom)
    out = await svc.apply("dummy")
    assert out["applied"] == []
    assert out["failed"] == [{"section": "timer_slots", "index": 1, "error": "device said no"}]
    assert audit.records[0]["result"] == "error"


@pytest.mark.asyncio
async def test_apply_propagation_of_transport_error_is_caught():
    async def boom(device, section, values, *, index=None):
        raise TransportError("bus timeout")

    svc = _service([_weekend_rule(fields={"target_soc_pct": 80})], apply_fn=boom)
    out = await svc.apply("dummy")
    assert out["failed"][0]["error"] == "bus timeout"


@pytest.mark.asyncio
async def test_apply_with_no_device_is_a_noop():
    svc = _service([_weekend_rule(fields={"target_soc_pct": 80})], devices=[])
    out = await svc.apply()
    assert out["applied"] == [] and out["failed"] == []


@pytest.mark.asyncio
async def test_apply_all_iterates_every_device():
    devs = [Device("a", NullTransport(), DummyProfile()), Device("b", NullTransport(), DummyProfile())]
    svc = _service([_weekend_rule(fields={"target_soc_pct": 80})], devices=devs)
    results = await svc.apply_all()
    assert {r["device_id"] for r in results} == {"a", "b"}
    assert all(r["applied"] for r in results)


@pytest.mark.asyncio
async def test_audit_failure_never_breaks_apply():
    class _BadAudit:
        async def record(self, *a, **k):
            raise RuntimeError("disk full")

    svc = _service([_weekend_rule(fields={"target_soc_pct": 80})], audit=_BadAudit())
    out = await svc.apply("dummy")  # must not raise
    assert out["applied"][0]["ok"] is True


@pytest.mark.asyncio
async def test_scheduler_ticks_then_stops_cleanly():
    svc = _service([_weekend_rule(fields={"target_soc_pct": 80})])
    svc._interval = 0.01
    ran = asyncio.Event()
    real = svc.apply_all

    async def spy(**kw):
        ran.set()
        return await real(**kw)

    svc.apply_all = spy
    await svc.start()
    await svc.start()  # idempotent — a second start doesn't spawn a second task
    await asyncio.wait_for(ran.wait(), timeout=1.0)
    await svc.stop()
    await svc.stop()  # idempotent


@pytest.mark.asyncio
async def test_scheduler_swallows_a_failing_tick():
    svc = _service([_weekend_rule(fields={"target_soc_pct": 80})])
    svc._interval = 0.01
    calls: list[int] = []

    async def boom(**kw):
        calls.append(1)
        raise RuntimeError("bad tick")

    svc.apply_all = boom
    await svc.start()
    for _ in range(200):
        if calls:
            break
        await asyncio.sleep(0.005)
    await svc.stop()
    assert calls  # the loop kept running despite the raised error

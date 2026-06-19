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
    def __init__(self, snapshot: dict | None = None, health: dict | None = None) -> None:
        self._snap = snapshot or {"devices": {}}
        self._health = health or {"devices": []}

    def snapshot(self) -> dict:
        return self._snap

    def health(self) -> dict:
        return self._health


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


class _AlertRepo:
    def __init__(self) -> None:
        self.inserts: list[dict] = []

    async def insert_alert(self, *, rule_id, device_id, severity, metric, value, message, fired_at):
        self.inserts.append({"rule_id": rule_id, "severity": severity,
                              "message": message, "device_id": device_id})
        return len(self.inserts)


def _weekend_rule(*, fields: dict, enabled=True, action_enabled=True, slot=1) -> dict:
    return {
        "id": "weekend", "name": "Weekend top-up", "match": "all", "enabled": enabled,
        "conditions": [{"kind": "day_of_week", "params": {"days": [5, 6]}}],
        "actions": [{"action_type": "set_setting",
                     "target": {"section": "timer_slots", "field": f, "index": slot},
                     "value": v, "enabled": action_enabled} for f, v in fields.items()],
    }


def _notify_rule(*, channels=("webhook",), message="Low SoC", debounce_s=0.0, enabled=True,
                 action_enabled=True) -> dict:
    return {
        "id": "notify_rule", "name": "Notify rule", "match": "all", "enabled": enabled,
        "conditions": [{"kind": "day_of_week", "params": {"days": [5, 6]}}],
        "actions": [{"action_type": "notify", "channels": list(channels), "message": message,
                     "severity": "warning", "debounce_s": debounce_s, "enabled": action_enabled,
                     "target": None, "value": None}],
    }


def _alert_rule(*, message="Device offline", severity="critical", debounce_s=0.0,
                enabled=True, action_enabled=True) -> dict:
    return {
        "id": "alert_rule", "name": "Alert rule", "match": "all", "enabled": enabled,
        "conditions": [{"kind": "day_of_week", "params": {"days": [5, 6]}}],
        "actions": [{"action_type": "alert", "message": message, "severity": severity,
                     "debounce_s": debounce_s, "enabled": action_enabled,
                     "channels": [], "target": None, "value": None}],
    }


def _service(rules: list[dict], *, devices=None, audit=None, alert_repo=None,
             apply_fn=None, post=None) -> AutomationService:
    device = devices if devices is not None else [Device("dummy", NullTransport(), DummyProfile())]
    return AutomationService(
        _Config({"automation_rules": rules}), _Poller(), _Registry(device),
        clock=lambda: _SAT, audit_repo=audit or _Audit(), alert_repo=alert_repo,
        interval_s=300.0, apply_fn=apply_fn, post=post,
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
    await svc.start(write_enabled=True)
    await svc.start(write_enabled=True)  # idempotent — a second start doesn't spawn a second task
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


# --- notify dispatch -----------------------------------------------------------
@pytest.mark.asyncio
async def test_notify_action_dispatches_to_channel():
    dispatched: list[dict] = []

    async def fake_post(url, payload=None, **kw):
        dispatched.append({"url": url, "payload": payload})

    cfg = _Config({"automation_rules": [_notify_rule(channels=("webhook",), message="Low SoC")],
                   "alert_channels": {"webhook": {"url": "http://hook.example/test"}}})
    device = Device("dummy", NullTransport(), DummyProfile())
    svc = AutomationService(cfg, _Poller(), _Registry([device]),
                            clock=lambda: _SAT, post=fake_post)
    await svc.reload_channels()
    out = await svc.apply("dummy", write=False)
    assert out["applied"] == []  # no set_setting actions
    assert len(dispatched) == 1
    assert dispatched[0]["payload"]["message"] == "Low SoC"
    assert dispatched[0]["payload"]["severity"] == "warning"


@pytest.mark.asyncio
async def test_notify_debounce_prevents_double_fire():
    dispatched: list[dict] = []

    async def fake_post(url, payload=None, **kw):
        dispatched.append(payload)

    cfg = _Config({"automation_rules": [_notify_rule(channels=("webhook",), debounce_s=600.0)],
                   "alert_channels": {"webhook": {"url": "http://hook.example/test"}}})
    device = Device("dummy", NullTransport(), DummyProfile())
    svc = AutomationService(cfg, _Poller(), _Registry([device]),
                            clock=lambda: _SAT, post=fake_post)
    await svc.reload_channels()
    await svc.apply("dummy", write=False)
    await svc.apply("dummy", write=False)  # second call within debounce window
    assert len(dispatched) == 1  # fired only once


@pytest.mark.asyncio
async def test_notify_channel_failure_does_not_break_apply():
    async def boom(url, payload=None, **kw):
        raise RuntimeError("network error")

    cfg = _Config({"automation_rules": [_notify_rule(channels=("webhook",))],
                   "alert_channels": {"webhook": {"url": "http://hook.example/test"}}})
    device = Device("dummy", NullTransport(), DummyProfile())
    svc = AutomationService(cfg, _Poller(), _Registry([device]),
                            clock=lambda: _SAT, post=boom)
    await svc.reload_channels()
    out = await svc.apply("dummy", write=False)  # must not raise
    assert out["device_id"] == "dummy"


@pytest.mark.asyncio
async def test_disabled_notify_action_does_not_dispatch():
    dispatched: list[dict] = []

    async def fake_post(url, payload=None, **kw):
        dispatched.append(payload)

    cfg = _Config({"automation_rules": [_notify_rule(channels=("webhook",), action_enabled=False)],
                   "alert_channels": {"webhook": {"url": "http://hook.example/test"}}})
    device = Device("dummy", NullTransport(), DummyProfile())
    svc = AutomationService(cfg, _Poller(), _Registry([device]),
                            clock=lambda: _SAT, post=fake_post)
    await svc.reload_channels()
    await svc.apply("dummy", write=False)
    assert dispatched == []


# --- alert inbox creation ------------------------------------------------------
@pytest.mark.asyncio
async def test_alert_action_creates_inbox_entry():
    alert_repo = _AlertRepo()
    svc = _service([_alert_rule(message="Device offline", severity="critical")],
                   alert_repo=alert_repo)
    await svc.apply("dummy", write=False)
    assert len(alert_repo.inserts) == 1
    rec = alert_repo.inserts[0]
    assert rec["rule_id"] == "alert_rule"
    assert rec["severity"] == "critical"
    assert rec["message"] == "Device offline"
    assert rec["device_id"] == "dummy"


@pytest.mark.asyncio
async def test_alert_debounce_prevents_double_insert():
    alert_repo = _AlertRepo()
    svc = _service([_alert_rule(message="offline", debounce_s=600.0)], alert_repo=alert_repo)
    await svc.apply("dummy", write=False)
    await svc.apply("dummy", write=False)
    assert len(alert_repo.inserts) == 1


@pytest.mark.asyncio
async def test_alert_repo_failure_does_not_break_apply():
    class _BadRepo:
        async def insert_alert(self, **kw):
            raise RuntimeError("db error")

    svc = _service([_alert_rule()], alert_repo=_BadRepo())
    out = await svc.apply("dummy", write=False)  # must not raise
    assert out["device_id"] == "dummy"


@pytest.mark.asyncio
async def test_alert_action_without_repo_is_a_noop():
    svc = _service([_alert_rule()], alert_repo=None)
    out = await svc.apply("dummy", write=False)
    assert out["device_id"] == "dummy"  # no error


# --- write=False skips set_setting writes -------------------------------------
@pytest.mark.asyncio
async def test_apply_write_false_skips_inverter_write():
    audit = _Audit()
    svc = _service([_weekend_rule(fields={"target_soc_pct": 80})], audit=audit)
    out = await svc.apply("dummy", write=False)
    assert out["applied"] == [] and out["failed"] == [] and audit.records == []


# --- synthetic metrics ---------------------------------------------------------
@pytest.mark.asyncio
async def test_stale_metric_injected_when_device_offline():
    """__stale_s__ should be the offline sentinel when health reports offline."""
    captured_ctx: list = []

    def fake_evaluate(rules, ctx, *, allow_list=None):
        captured_ctx.append(ctx)
        from app.automation.rules import AutomationDecision
        return AutomationDecision()

    from unittest.mock import patch
    from app.automation import service as svc_mod
    device = Device("dummy", NullTransport(), DummyProfile())
    poller = _Poller(
        snapshot={"devices": {"dummy": {"metrics": {}}}},
        health={"devices": [{"device_id": "dummy", "online": False, "last_sample_age_s": None}]},
    )
    cfg = _Config({"automation_rules": []})
    svc = AutomationService(cfg, poller, _Registry([device]), clock=lambda: _SAT)
    with patch.object(svc_mod, "evaluate_rules", fake_evaluate):
        await svc.apply("dummy", write=False)
    assert captured_ctx[0].metrics["__stale_s__"] == 1e9


@pytest.mark.asyncio
async def test_fault_count_metric_injected():
    """__fault_count__ should count active fault codes from the snapshot."""
    captured_ctx: list = []

    def fake_evaluate(rules, ctx, *, allow_list=None):
        captured_ctx.append(ctx)
        from app.automation.rules import AutomationDecision
        return AutomationDecision()

    from unittest.mock import patch
    from app.automation import service as svc_mod
    device = Device("dummy", NullTransport(), DummyProfile())
    poller = _Poller(
        snapshot={"devices": {"dummy": {"metrics": {"inverter_fault_codes": ["F01", "F02"]}}}},
        health={"devices": [{"device_id": "dummy", "online": True, "last_sample_age_s": 5.0}]},
    )
    cfg = _Config({"automation_rules": []})
    svc = AutomationService(cfg, poller, _Registry([device]), clock=lambda: _SAT)
    with patch.object(svc_mod, "evaluate_rules", fake_evaluate):
        await svc.apply("dummy", write=False)
    assert captured_ctx[0].metrics["__fault_count__"] == 2.0
    assert captured_ctx[0].metrics["__stale_s__"] == 5.0


# --- message template rendering -----------------------------------------------
@pytest.mark.asyncio
async def test_notify_message_template_rendered_with_metrics():
    """``{metric_key}`` placeholders in the notify message are replaced with live values."""
    dispatched: list[dict] = []

    async def fake_post(url, payload=None, **kw):
        dispatched.append(payload)

    cfg = _Config({
        "automation_rules": [_notify_rule(channels=("webhook",),
                                          message="Battery SoC is {battery_soc_pct:.1f}%")],
        "alert_channels": {"webhook": {"url": "http://hook.example/test"}},
    })
    device = Device("dummy", NullTransport(), DummyProfile())
    # DummyProfile reports battery_soc_pct; inject a known value via a snapshot stub.
    poller = _Poller(snapshot={
        "devices": {"dummy": {"metrics": {"battery_soc_pct": 42.5}}},
    })
    svc = AutomationService(cfg, poller, _Registry([device]), clock=lambda: _SAT, post=fake_post)
    await svc.reload_channels()
    await svc.apply("dummy", write=False)
    assert len(dispatched) == 1
    assert dispatched[0]["message"] == "Battery SoC is 42.5%"


@pytest.mark.asyncio
async def test_alert_message_template_rendered_with_metrics():
    """``{metric_key}`` placeholders in the alert message are replaced with live values."""
    alert_repo = _AlertRepo()
    poller = _Poller(snapshot={
        "devices": {"dummy": {"metrics": {"battery_soc_pct": 17.3}}},
    })
    svc = _service(
        [_alert_rule(message="SoC low: {battery_soc_pct:.0f}%")],
        alert_repo=alert_repo,
    )
    svc._poller = poller
    await svc.apply("dummy", write=False)
    assert len(alert_repo.inserts) == 1
    assert alert_repo.inserts[0]["message"] == "SoC low: 17%"


def test_render_message_unknown_key_left_in_place():
    """Unknown metric keys are preserved as ``{key}`` rather than raising."""
    from app.automation.service import _render_message
    result = _render_message("SoC={battery_soc_pct} fault={no_such_metric}", {"battery_soc_pct": 55.0})
    assert result == "SoC=55.0 fault={no_such_metric}"


def test_render_message_bad_format_spec_falls_back():
    """A malformed format spec returns the raw template rather than raising."""
    from app.automation.service import _render_message
    result = _render_message("{battery_soc_pct:.1fXXX}", {"battery_soc_pct": 42.0})
    assert result == "{battery_soc_pct:.1fXXX}"


def test_render_message_no_placeholders_unchanged():
    """Messages with no ``{`` are returned as-is (fast path, no format_map call)."""
    from app.automation.service import _render_message
    assert _render_message("all clear", {"battery_soc_pct": 99.0}) == "all clear"

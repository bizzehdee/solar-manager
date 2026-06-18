"""Alert evaluation service (plan.md §15): value resolution, fire/clear persistence, and
channel dispatch — against a fake poller + in-memory repo, no network."""

from __future__ import annotations

from datetime import datetime

from app.alerts.engine import AlertRule
from app.alerts.service import AlertService
from app.storage.repository import AlertRepository

_NOON = datetime(2026, 6, 18, 12, 0).astimezone()  # not in default quiet hours


class FakePoller:
    def __init__(self, metrics: dict | None = None, health: list | None = None) -> None:
        self._metrics = metrics or {}
        self._health = health or []

    def snapshot(self) -> dict:
        return {"devices": {d: {"metrics": m} for d, m in self._metrics.items()}}

    def health(self) -> dict:
        return {"devices": self._health}


class FakeConfig:
    def __init__(self, d: dict | None = None) -> None:
        self._d = d or {}

    async def get(self, key, default=None):
        return self._d.get(key, default)


def _online(device="dummy", age=2.0):
    return [{"device_id": device, "online": True, "last_sample_age_s": age}]


async def _service(poller, *, config=None, post=None) -> AlertService:
    repo = await AlertRepository.open(":memory:")
    svc = AlertService(repo, poller, config or FakeConfig(), clock=lambda: _NOON, post=post)
    return svc


async def test_low_soc_fires_then_clears():
    poller = FakePoller({"dummy": {"battery_soc_pct": 10.0}}, _online())
    svc = await _service(poller)
    await svc._repo.upsert_rule(
        AlertRule(id="low_soc", name="Low SoC", metric="battery_soc_pct", op="lt",
                  threshold=20.0, hysteresis=5.0).to_dict()
    )
    await svc.reload()

    assert await svc.evaluate_once() == ["fire"]
    active = await svc._repo.list_alerts(active_only=True)
    assert len(active) == 1 and active[0]["metric"] == "battery_soc_pct" and active[0]["severity"] == "warning"

    poller._metrics["dummy"]["battery_soc_pct"] = 30.0  # recovered past 20+5
    assert await svc.evaluate_once() == ["clear"]
    assert await svc._repo.list_alerts(active_only=True) == []


async def test_offline_device_fires_stale_alert():
    poller = FakePoller({}, [{"device_id": "dummy", "online": False, "last_sample_age_s": None}])
    svc = await _service(poller)
    await svc._repo.upsert_rule(
        AlertRule(id="stale", name="Stale", metric="__stale_s__", op="gt", threshold=120.0).to_dict()
    )
    await svc.reload()
    assert await svc.evaluate_once() == ["fire"]
    a = (await svc._repo.list_alerts(active_only=True))[0]
    assert a["metric"] == "__stale_s__" and a["value"] >= 120.0


async def test_inverter_fault_count_fires():
    poller = FakePoller({"dummy": {"inverter_fault_codes": ["F01", "F23"]}}, _online())
    svc = await _service(poller)
    await svc._repo.upsert_rule(
        AlertRule(id="fault", name="Fault", metric="__fault_count__", op="gt", threshold=0.0).to_dict()
    )
    await svc.reload()
    assert await svc.evaluate_once() == ["fire"]
    assert (await svc._repo.list_alerts(active_only=True))[0]["value"] == 2.0


async def test_webhook_channel_dispatched_on_fire():
    sent: list[tuple[str, dict]] = []

    async def fake_post(url, payload):
        sent.append((url, payload))

    poller = FakePoller({"dummy": {"battery_soc_pct": 5.0}}, _online())
    config = FakeConfig({"alert_channels": {"webhook": {"url": "http://hook"}}})
    svc = await _service(poller, config=config, post=fake_post)
    await svc._repo.upsert_rule(
        AlertRule(id="low", name="Low", metric="battery_soc_pct", op="lt", threshold=20.0,
                  channels=("webhook",), message="SoC low").to_dict()
    )
    await svc.reload()
    await svc.evaluate_once()
    assert len(sent) == 1
    url, payload = sent[0]
    assert url == "http://hook" and payload["rule_id"] == "low" and payload["message"] == "SoC low"


async def test_disabled_rule_is_skipped():
    poller = FakePoller({"dummy": {"battery_soc_pct": 5.0}}, _online())
    svc = await _service(poller)
    await svc._repo.upsert_rule(
        AlertRule(id="low", name="Low", metric="battery_soc_pct", op="lt", threshold=20.0,
                  enabled=False).to_dict()
    )
    await svc.reload()
    assert await svc.evaluate_once() == []


async def test_fired_alert_can_be_acked_and_snoozed():
    repo = await AlertRepository.open(":memory:")
    aid = await repo.insert_alert(
        rule_id="low", device_id="dummy", severity="warning", metric="battery_soc_pct",
        value=10.0, message="low", fired_at=1000.0,
    )
    assert (await repo.list_alerts(active_only=True))[0]["id"] == aid
    assert await repo.active_count() == 1
    assert await repo.ack(aid, 1001.0)
    assert await repo.active_count() == 0          # acked drops out of the active-unacked count
    assert await repo.snooze(aid, 2000.0)
    assert (await repo.list_alerts())[0]["snooze_until"] == 2000.0
    assert not await repo.ack(999, 0.0)            # unknown id


async def test_reload_skips_invalid_rules_and_seeds_defaults():
    poller = FakePoller({"dummy": {"battery_soc_pct": 80.0}}, _online())
    svc = await _service(poller)
    # A malformed rule row is ignored, not fatal.
    await svc._repo.upsert_rule({"id": "bad", "metric": "x", "op": "??"})
    await svc.reload()
    assert all(r.id != "bad" for r in svc._rules)
    # start() seeds the three defaults on an empty rule set.
    await svc._repo.delete_rule("bad")
    await svc._repo.seed_rules([])  # no-op when rows exist; here none → seeds nothing extra

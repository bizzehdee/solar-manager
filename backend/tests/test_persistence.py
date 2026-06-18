"""Persistence service: decoupled persist + rollup/prune maintenance (task T042/T043)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import Reading
from app.persistence import PersistenceService
from app.storage.repository import SqliteHistoryRepository


class FakePoller:
    def __init__(self, readings):
        self._readings = readings

    def latest_readings(self):
        return list(self._readings)


def _reading(epoch, **m):
    return Reading(ts=datetime.fromtimestamp(epoch, tz=timezone.utc), device_id="d", metrics=m)


async def test_persist_once_writes_then_dedups_same_timestamp():
    repo = await SqliteHistoryRepository.open(":memory:")
    poller = FakePoller([_reading(100.0, pv_power_w=3000.0, battery_soc_pct=80)])
    svc = PersistenceService(repo, poller)

    assert await svc.persist_once() == 2          # two numeric metrics stored
    assert await svc.persist_once() == 0          # same ts -> skipped, no duplicate rows
    assert [p.value for p in await repo.query("d", "pv_power_w", 0, 200, "raw")] == [3000.0]


async def test_persist_once_writes_new_timestamp():
    repo = await SqliteHistoryRepository.open(":memory:")
    poller = FakePoller([_reading(100.0, pv_power_w=1.0)])
    svc = PersistenceService(repo, poller)
    await svc.persist_once()
    poller._readings = [_reading(200.0, pv_power_w=2.0)]
    assert await svc.persist_once() == 1
    assert len(await repo.query("d", "pv_power_w", 0, 300, "raw")) == 2


async def test_maintain_aggregates_then_prunes():
    repo = await SqliteHistoryRepository.open(":memory:")
    # Two days of data; "now" is day 2, retention 1 day -> day-1 raw pruned, rollups kept.
    day = 86400.0
    for t in (0.0, 60.0, day, day + 60.0):
        await repo.write_reading(_reading(t, pv_power_w=t))
    now = datetime.fromtimestamp(day + 120.0, tz=timezone.utc)
    svc = PersistenceService(repo, poller=FakePoller([]), retention_days=1.0, clock=lambda: now)

    await svc.maintain_once()
    # Day-1 raw (t=0,60) pruned; day-2 raw kept.
    raw = await repo.query("d", "pv_power_w", 0.0, 3 * day, "raw")
    assert [p.ts for p in raw] == [day, day + 60.0]
    # Daily rollups exist for both days (computed before the prune).
    assert len(await repo.query("d", "pv_power_w", 0.0, 3 * day, "1d")) == 2


async def test_persist_failure_does_not_raise(monkeypatch):
    repo = await SqliteHistoryRepository.open(":memory:")
    svc = PersistenceService(repo, FakePoller([_reading(1.0, pv_power_w=1.0)]))

    async def boom(_):
        raise RuntimeError("disk full")

    monkeypatch.setattr(repo, "write_reading", boom)
    assert await svc.persist_once() == 0  # swallowed, returns 0

"""SQLite repository: persist, roll up, query, prune, device CRUD (plan.md §5;
tasks T040/T041/T042/T043/T044/T047)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import Reading
from app.storage import connect, run_migrations
from app.storage.migrations import SCHEMA_VERSION
from app.storage.repository import (
    DeviceConfigRepository,
    SqliteHistoryRepository,
    open_repositories,
)


def _reading(epoch: float, **metrics) -> Reading:
    return Reading(ts=datetime.fromtimestamp(epoch, tz=timezone.utc), device_id="d", metrics=metrics)


# --- migrations (T041) ------------------------------------------------------------
def test_migrations_apply_and_are_idempotent():
    conn = connect(":memory:")
    assert run_migrations(conn) == SCHEMA_VERSION
    # Second run is a no-op (version unchanged), tables still present.
    assert run_migrations(conn) == SCHEMA_VERSION
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"samples", "rollup_5m", "rollup_1h", "rollup_1d", "devices", "meta"} <= tables


# --- history repo (T042/T044) -----------------------------------------------------
async def test_write_skips_non_numeric_metrics():
    repo = await SqliteHistoryRepository.open(":memory:")
    n = await repo.write_reading(
        _reading(100.0, pv_power_w=3000.0, inverter_status="running", battery_soc_pct=80)
    )
    assert n == 2  # the string status is not persisted
    assert await repo.latest("d", "pv_power_w") == 3000.0
    assert await repo.metrics("d") == ["battery_soc_pct", "pv_power_w"]


async def test_query_raw_samples_in_range():
    repo = await SqliteHistoryRepository.open(":memory:")
    for t in (10.0, 20.0, 30.0):
        await repo.write_reading(_reading(t, pv_power_w=t))
    pts = await repo.query("d", "pv_power_w", 15.0, 25.0, "raw")
    assert [p.value for p in pts] == [20.0]


async def test_aggregate_rolls_up_into_buckets():
    repo = await SqliteHistoryRepository.open(":memory:")
    # Three samples in one 5-minute bucket (0..300).
    for t, v in ((0.0, 100.0), (60.0, 200.0), (120.0, 300.0)):
        await repo.write_reading(_reading(t, pv_power_w=v))
    written = await repo.aggregate()
    assert written["5m"] == 1
    [pt] = await repo.query("d", "pv_power_w", 0.0, 300.0, "5m")
    assert pt.value == 200.0 and pt.min == 100.0 and pt.max == 300.0 and pt.last == 300.0 and pt.n == 3


async def test_aggregate_is_incremental_and_recomputes_open_bucket():
    repo = await SqliteHistoryRepository.open(":memory:")
    await repo.write_reading(_reading(0.0, pv_power_w=100.0))
    await repo.aggregate()
    # A later sample lands in the same 5m bucket; re-aggregating updates it in place.
    await repo.write_reading(_reading(60.0, pv_power_w=300.0))
    await repo.aggregate()
    [pt] = await repo.query("d", "pv_power_w", 0.0, 300.0, "5m")
    assert pt.value == 200.0 and pt.n == 2  # value == bucket average


async def test_prune_removes_raw_keeps_rollups():
    repo = await SqliteHistoryRepository.open(":memory:")
    for t in (0.0, 60.0, 120.0):
        await repo.write_reading(_reading(t, pv_power_w=t))
    await repo.aggregate()
    removed = await repo.prune(100.0)  # drop samples before t=100
    assert removed == 2
    assert [p.value for p in await repo.query("d", "pv_power_w", 0.0, 300.0, "raw")] == [120.0]
    # Rollup survives the prune.
    assert len(await repo.query("d", "pv_power_w", 0.0, 300.0, "5m")) == 1


async def test_query_rejects_unknown_resolution():
    repo = await SqliteHistoryRepository.open(":memory:")
    with pytest.raises(ValueError, match="resolution"):
        await repo.query("d", "pv_power_w", 0.0, 1.0, "weekly")


async def test_latest_absent_metric_is_none():
    repo = await SqliteHistoryRepository.open(":memory:")
    assert await repo.latest("d", "nope") is None


# --- device config repo (T047) ----------------------------------------------------
async def test_device_crud_roundtrip():
    repo = await DeviceConfigRepository.open(":memory:")
    assert await repo.count() == 0
    created = await repo.create(
        {"id": "inv1", "name": "Inverter 1", "transport": "modbus_rtu",
         "profile": "sunsynk-8k-sg05lp1", "params": {"port": "/dev/ttyUSB0", "slave_id": 1}}
    )
    assert created["params"]["port"] == "/dev/ttyUSB0"
    assert created["enabled"] is True
    assert await repo.count() == 1

    fetched = await repo.get("inv1")
    assert fetched["name"] == "Inverter 1" and fetched["transport"] == "modbus_rtu"

    updated = await repo.update("inv1", {"name": "Renamed", "enabled": False})
    assert updated["name"] == "Renamed" and updated["enabled"] is False
    assert updated["params"]["port"] == "/dev/ttyUSB0"  # untouched fields preserved

    assert await repo.update("missing", {"name": "x"}) is None
    assert await repo.delete("inv1") is True
    assert await repo.delete("inv1") is False
    assert await repo.list() == []


async def test_open_repositories_shares_one_connection():
    history, config, _app_config, _audit = await open_repositories(":memory:")
    # Both repos see the same DB: a device written via config is visible to a fresh list,
    # and history writes work on the same connection without cross-thread errors.
    await config.create({"id": "d", "name": "D", "transport": "dummy"})
    await history.write_reading(_reading(1.0, pv_power_w=5.0))
    assert (await config.count()) == 1
    assert await history.latest("d", "pv_power_w") == 5.0

"""Daily statistics engine (plan.md §3; tasks T050/T052/T055)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import Reading
from app.stats import StatsService
from app.storage.repository import open_repositories

DAY = datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc).timestamp()  # midnight UTC = day bucket


def _reading(epoch, **metrics):
    return Reading(ts=datetime.fromtimestamp(epoch, tz=timezone.utc), device_id="d", metrics=metrics)


async def _seed_day(history):
    """A full day of cumulative counters (hourly), plus a couple of PV power points."""
    counters = {
        "today_pv_wh": [0, 3000, 7000, 10000],
        "today_load_wh": [0, 2000, 5000, 8000],
        "today_grid_import_wh": [0, 500, 1500, 2000],
        "today_grid_export_wh": [0, 1000, 3000, 4000],
        "today_batt_charge_wh": [0, 1000, 2000, 3000],
        "today_batt_discharge_wh": [0, 900, 1800, 2700],
    }
    for h in range(4):
        await history.write_reading(_reading(DAY + h * 3600, **{m: vals[h] for m, vals in counters.items()}))
    await history.write_reading(_reading(DAY + 5 * 3600, pv_power_w=5500.0))
    await history.write_reading(_reading(DAY + 6 * 3600, pv_power_w=4000.0))
    await history.aggregate()


async def test_daily_energy_totals_and_kpis():
    history, _devices, cfg, _audit, _alerts = await open_repositories(":memory:")
    await _seed_day(history)
    stats = StatsService(history, cfg)

    s = await stats.daily("d", DAY)
    assert s.date == "2026-06-18"
    assert s.energy_wh["pv"] == 10000.0
    assert s.energy_wh["load"] == 8000.0
    assert s.energy_wh["import"] == 2000.0
    assert s.energy_wh["export"] == 4000.0
    # self-consumption = (pv - export)/pv = 60%; self-sufficiency = (load - import)/load = 75%
    assert s.self_consumption_pct == 60.0
    assert s.self_sufficiency_pct == 75.0
    # round-trip efficiency = discharge/charge = 2700/3000
    assert s.round_trip_efficiency == 0.9
    assert s.peak_pv_w == 5500.0  # max PV power across the day


async def test_daily_economics_with_flat_tariff():
    history, _devices, cfg, _audit, _alerts = await open_repositories(":memory:")
    await _seed_day(history)
    await cfg.set("tariff", {"import_rate": 0.30, "export_rate": 0.05, "currency": "GBP"})
    await cfg.set("economics", {"co2_intensity_g_per_kwh": 200.0})
    stats = StatsService(history, cfg)

    s = await stats.daily("d", DAY)
    econ = s.economics
    assert econ["import_cost"] == 0.6      # 2 kWh * 0.30
    assert econ["export_revenue"] == 0.2   # 4 kWh * 0.05
    assert econ["net_cost"] == 0.4
    assert econ["baseline_cost"] == 2.4    # 8 kWh load * 0.30 (all-grid)
    assert econ["savings"] == 2.0          # 2.4 - 0.4
    assert econ["co2_avoided_kg"] == 1.2   # 6 kWh self-consumed * 200 g/kWh
    assert s.currency == "GBP"


async def test_daily_economics_with_standing_charge_and_tou_import():
    history, _devices, cfg, _audit, _alerts = await open_repositories(":memory:")
    await _seed_day(history)
    # TOU import (cheap 00–06, pricier after) + flat export + a 60.75p/day standing charge.
    await cfg.set("tariff", {
        "currency": "GBP",
        "standing_charge": 0.6075,
        "import_rate": {"flat": 0.30, "windows": [{"start_hour": 0, "end_hour": 6, "rate": 0.09}]},
        "export_rate": 0.05,
    })
    stats = StatsService(history, cfg)

    s = await stats.daily("d", DAY)
    econ = s.economics
    # Standing charge is surfaced and folded into the real bill + baseline, cancelling in savings.
    assert econ["standing_charge"] == 0.6075
    # All seeded import deltas land in the 00–06 cheap window → 2 kWh * 0.09 = 0.18.
    assert econ["import_cost"] == 0.18
    assert econ["net_cost"] == round(0.18 - 0.2 + 0.6075, 4)
    # savings independent of the standing charge (it's in both net and baseline).
    assert econ["savings"] == round(econ["baseline_cost"] - econ["net_cost"], 4)


async def test_daily_empty_day_is_safe():
    history, _devices, cfg, _audit, _alerts = await open_repositories(":memory:")
    stats = StatsService(history, cfg)
    s = await stats.daily("d", DAY)
    assert s.energy_wh["pv"] == 0.0
    assert s.self_consumption_pct is None   # undefined with no PV
    assert s.round_trip_efficiency is None
    assert s.economics["savings"] == 0.0

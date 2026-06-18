"""Battery SoC projection (task T062)."""

from __future__ import annotations

from app.forecast.battery import (
    BatterySpec,
    first_time_at_or_above,
    first_time_at_or_below,
    project_soc,
)

BATT = BatterySpec(capacity_wh=10000.0, min_soc_pct=10.0, max_soc_pct=100.0,
                   max_charge_w=5000.0, max_discharge_w=5000.0)


def test_surplus_charges_battery():
    [p] = project_soc(50.0, [(0.0, 2000.0, 0.0)], BATT)  # 2 kW surplus for 1h
    assert p.soc_pct == 70.0          # +2000 Wh on a 10 kWh pack from 50%
    assert p.battery_w == 2000.0
    assert p.grid_w == 0.0


def test_deficit_discharges_battery():
    [p] = project_soc(50.0, [(0.0, 0.0, 2000.0)], BATT)  # 2 kW deficit for 1h
    assert p.soc_pct == 30.0
    assert p.battery_w == -2000.0
    assert p.grid_w == 0.0


def test_charge_capped_by_headroom_spills_to_grid_export():
    # Start at 95% (= 9500 Wh), 5 kW surplus: only 500 Wh headroom this hour -> rest exports.
    [p] = project_soc(95.0, [(0.0, 5000.0, 0.0)], BATT)
    assert p.soc_pct == 100.0
    assert p.battery_w == 500.0        # limited by headroom
    assert p.grid_w == -4500.0         # surplus beyond charge is exported


def test_discharge_capped_by_available_then_imports():
    # Start at min (10% = 1000 Wh): nothing to discharge -> deficit met by grid import.
    [p] = project_soc(10.0, [(0.0, 0.0, 3000.0)], BATT)
    assert p.soc_pct == 10.0
    assert p.battery_w == 0.0
    assert p.grid_w == 3000.0          # imported


def test_depletion_and_full_detection():
    # Steady 1 kW deficit from 30% drains toward the 10% floor.
    # step@t=0: 30%→20%; step@t=3600: 20%→10% (reaches floor).
    hourly = [(float(h * 3600), 0.0, 1000.0) for h in range(5)]
    pts = project_soc(30.0, hourly, BATT)
    dep = first_time_at_or_below(pts, BATT.min_soc_pct)
    assert dep == 3600.0

    charge = [(float(h * 3600), 5000.0, 0.0) for h in range(3)]
    full = first_time_at_or_above(project_soc(80.0, charge, BATT), BATT.max_soc_pct)
    assert full is not None


def test_battery_spec_from_dict_defaults():
    b = BatterySpec.from_dict({})
    assert b.capacity_wh == 10000.0 and b.min_soc_pct == 10.0


def test_daily_summary_groups_by_calendar_day():
    from datetime import datetime, timezone

    from app.forecast.service import daily_summary

    d1 = datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc).timestamp()
    d2 = d1 + 86400
    generation = [
        {"ts": d1, "pv_w": 0.0}, {"ts": d1 + 3600, "pv_w": 2000.0}, {"ts": d1 + 7200, "pv_w": 0.0},
        {"ts": d2, "pv_w": 0.0}, {"ts": d2 + 3600, "pv_w": 1000.0},
    ]
    soc = [
        {"ts": d1, "soc_pct": 50.0}, {"ts": d1 + 3600, "soc_pct": 8.0},
        {"ts": d2, "soc_pct": 60.0}, {"ts": d2 + 3600, "soc_pct": 70.0},
    ]
    rows = daily_summary(generation, soc, min_soc_pct=10.0)
    assert [r["date"] for r in rows] == ["2026-06-21", "2026-06-22"]
    # Day 1: trapezoid 0->2000->0 over two hours = 2000 Wh; SoC dipped to floor.
    assert rows[0]["expected_wh"] == 2000.0
    assert rows[0]["min_soc_pct"] == 8.0 and rows[0]["battery_depleted"] is True
    assert rows[1]["battery_depleted"] is False and rows[1]["max_soc_pct"] == 70.0

"""Automation planning engine — pure decision logic (plan.md §18; task L03a).

A §21 critical-logic module: cheapest/peak-window detection (incl. midnight wrap), the
forecast-aware target-SoC math, the saving estimate, and every no-action path.
"""

from __future__ import annotations

from app.automation import planner
from app.automation.planner import AutomationStrategy
from app.forecast.battery import BatterySpec
from app.tariff import RateSchedule


def _battery(**over) -> BatterySpec:
    base = dict(capacity_wh=10000.0, min_soc_pct=10.0, max_soc_pct=100.0, max_charge_w=5000.0, max_discharge_w=5000.0)
    base.update(over)
    return BatterySpec(**base)


# A typical Octopus-Go-ish tariff: cheap 00:00–05:00, pricey otherwise.
def _tou() -> RateSchedule:
    return RateSchedule.from_dict({
        "flat": 0.30,
        "windows": [
            {"start_hour": 0, "end_hour": 5, "rate": 0.08},   # cheap overnight
            {"start_hour": 16, "end_hour": 19, "rate": 0.45},  # evening peak
        ],
    })


# --- window detection -------------------------------------------------------

def test_cheapest_and_peak_window():
    sched = _tou()
    assert planner.cheapest_window(sched) == (0, 5, 0.08)
    assert planner.peak_window(sched) == (16, 19, 0.45)


def test_cheapest_window_wraps_midnight():
    # Cheap rate spans 23:00 → 02:00 (wraps). end is exclusive and < start on a wrap.
    sched = RateSchedule.from_dict({
        "flat": 0.30,
        "windows": [{"start_hour": 23, "end_hour": 2, "rate": 0.10}],
    })
    start, end, rate = planner.cheapest_window(sched)
    assert (start, end, rate) == (23, 2, 0.10)


# --- target-SoC math --------------------------------------------------------

def test_target_soc_high_on_poor_forecast():
    # Big deficit (little sun, lots of load) -> charge toward full.
    pct = planner.overnight_target_soc_pct(expected_pv_wh=1000, expected_load_wh=12000, battery=_battery())
    assert pct == 100.0


def test_target_soc_low_on_sunny_forecast():
    # Surplus day -> only the reserve is needed (no grid top-up beyond it).
    pct = planner.overnight_target_soc_pct(expected_pv_wh=20000, expected_load_wh=8000, battery=_battery())
    assert pct == 20.0  # == day_reserve default


def test_target_soc_scales_with_deficit_and_rounds_to_step():
    # deficit 3000 Wh / 10 kWh = 30% on top of 20% reserve = 50%.
    pct = planner.overnight_target_soc_pct(expected_pv_wh=5000, expected_load_wh=8000, battery=_battery())
    assert pct == 50.0


def test_target_soc_respects_battery_max():
    pct = planner.overnight_target_soc_pct(
        expected_pv_wh=0, expected_load_wh=99999, battery=_battery(max_soc_pct=90.0)
    )
    assert pct == 90.0


# --- full plan --------------------------------------------------------------

def test_plan_proposes_charge_and_reserve_slots():
    plan = planner.plan_timer(
        current_slots=[],
        import_schedule=_tou(),
        battery=_battery(),
        current_soc_pct=30.0,
        expected_pv_wh=5000,
        expected_load_wh=8000,
    )
    assert plan.action is True
    by_index = {c.index: c.fields for c in plan.changes}
    # Slot 0 grid-charges in the cheap window to the forecast target (50%).
    assert by_index[0]["charge_from_grid"] is True
    assert by_index[0]["start_time"] == "00:00"
    assert by_index[0]["target_soc_pct"] == 50
    # Slot 1 reserves the battery from the peak start, no grid charge.
    assert by_index[1]["charge_from_grid"] is False
    assert by_index[1]["start_time"] == "16:00"
    assert plan.estimated_saving > 0.0


def test_plan_saving_uses_rate_spread():
    plan = planner.plan_timer(
        current_slots=[], import_schedule=_tou(), battery=_battery(),
        current_soc_pct=20.0, expected_pv_wh=5000, expected_load_wh=8000,
    )
    # shifted energy = min(charge headroom, peak-hours load); valued at spread (0.45-0.08).
    # headroom = (50-20)% * 10kWh = 3000 Wh; peak load = 8000 * 3/24 = 1000 Wh -> 1000 Wh shifted.
    assert plan.estimated_saving == round(1000.0 / 1000.0 * (0.45 - 0.08), 4)


def test_no_action_on_flat_tariff():
    plan = planner.plan_timer(
        current_slots=[], import_schedule=RateSchedule.from_dict(0.30), battery=_battery(),
        current_soc_pct=50.0, expected_pv_wh=5000, expected_load_wh=8000,
    )
    assert plan.action is False
    assert "flat" in plan.summary.lower()


def test_no_action_when_spread_below_threshold():
    sched = RateSchedule.from_dict({"flat": 0.30, "windows": [{"start_hour": 0, "end_hour": 5, "rate": 0.28}]})
    plan = planner.plan_timer(
        current_slots=[], import_schedule=sched, battery=_battery(),
        current_soc_pct=50.0, expected_pv_wh=5000, expected_load_wh=8000,
    )
    assert plan.action is False
    assert "threshold" in plan.summary.lower()


def test_no_action_when_solar_covers_load():
    plan = planner.plan_timer(
        current_slots=[], import_schedule=_tou(), battery=_battery(),
        current_soc_pct=50.0, expected_pv_wh=20000, expected_load_wh=8000,
    )
    assert plan.action is False
    assert "solar covers" in plan.summary.lower()


def test_no_action_when_timer_already_optimal():
    sched = _tou()
    # Pre-seed slots exactly as the planner would propose for this scenario (target 50%).
    current = [
        {"start_time": "00:00", "charge_from_grid": True, "target_soc_pct": 50, "power_w": 5000},
        {"start_time": "16:00", "charge_from_grid": False, "target_soc_pct": 20, "power_w": 5000},
    ]
    plan = planner.plan_timer(
        current_slots=current, import_schedule=sched, battery=_battery(),
        current_soc_pct=30.0, expected_pv_wh=5000, expected_load_wh=8000,
    )
    assert plan.action is False
    assert "already" in plan.summary.lower()


def test_as_dict_is_json_shaped():
    plan = planner.plan_timer(
        current_slots=[], import_schedule=_tou(), battery=_battery(),
        current_soc_pct=30.0, expected_pv_wh=5000, expected_load_wh=8000,
    )
    d = plan.as_dict()
    assert d["action"] is True and isinstance(d["changes"], list)
    assert set(d) == {"strategy", "action", "summary", "changes", "estimated_saving", "inputs"}
    assert d["changes"][0]["index"] == 0

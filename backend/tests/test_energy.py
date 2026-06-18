"""Energy accounting math (plan.md §5, §10; task T046) — §21 critical logic."""

from __future__ import annotations

from app import energy


def test_integrate_constant_power():
    # 1000 W held for 1 hour = 1000 Wh.
    pts = [(0.0, 1000.0), (3600.0, 1000.0)]
    assert energy.integrate_wh(pts) == 1000.0


def test_integrate_trapezoid():
    # Ramp 0 -> 2000 W over 1 h: average 1000 W -> 1000 Wh.
    assert energy.integrate_wh([(0.0, 0.0), (3600.0, 2000.0)]) == 1000.0


def test_integrate_skips_long_gaps():
    # A 2-hour gap between samples is not bridged (would fabricate energy).
    pts = [(0.0, 1000.0), (7200.0, 1000.0)]
    assert energy.integrate_wh(pts) == 0.0


def test_integrate_needs_two_points():
    assert energy.integrate_wh([]) == 0.0
    assert energy.integrate_wh([(0.0, 500.0)]) == 0.0


def test_integrate_ignores_nonpositive_dt():
    # Out-of-order/duplicate timestamps contribute nothing rather than negative energy.
    assert energy.integrate_wh([(10.0, 1000.0), (10.0, 1000.0)]) == 0.0


def test_counter_simple_accumulation():
    # Monotonic daily counter: total = last - first across forward steps.
    pts = [(0.0, 100.0), (60.0, 250.0), (120.0, 400.0)]
    assert energy.counter_to_wh(pts) == 300.0


def test_counter_handles_midnight_reset():
    # Counter climbs to 5000, resets to ~0 at midnight, climbs again to 1200.
    pts = [(0.0, 4000.0), (60.0, 5000.0), (120.0, 50.0), (180.0, 1200.0)]
    # 1000 (4000->5000) + 50 (reset, counted from 0) + 1150 (50->1200) = 2200
    assert energy.counter_to_wh(pts) == 2200.0


def test_counter_ignores_small_dip_as_noise():
    # A small dip (not below half the previous) is jitter, not a reset: contributes 0.
    pts = [(0.0, 1000.0), (60.0, 980.0), (120.0, 1100.0)]
    # 980 is > 1000*0.5 so not a reset; 980<1000 ignored; then 980->1100 = +120
    assert energy.counter_to_wh(pts) == 120.0


def test_counter_needs_two_points():
    assert energy.counter_to_wh([(0.0, 500.0)]) == 0.0


def test_self_consumption_and_ratios():
    assert energy.self_consumption_wh(10000, 3000) == 7000
    assert energy.self_consumption_wh(1000, 2000) == 0  # clamped
    assert energy.self_consumption_ratio(10000, 3000) == 0.7
    assert energy.self_consumption_ratio(0, 0) is None
    assert energy.self_sufficiency_ratio(8000, 2000) == 0.75
    assert energy.self_sufficiency_ratio(0, 0) is None

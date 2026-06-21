"""Derived (calculated) metrics — task L16-1."""

from __future__ import annotations

from app.derived import DERIVED_METRICS, derive_metrics


def test_energy_ratio_metrics_from_today_counters():
    m = {
        "today_pv_wh": 10_000,
        "today_grid_export_wh": 2_500,   # self-consumed PV = 7500 → 75%
        "today_load_wh": 8_000,
        "today_grid_import_wh": 2_000,   # self-supplied = 6000 → 75%
        "today_batt_charge_wh": 4_000,
        "today_batt_discharge_wh": 3_400,  # RTE = 85%
    }
    d = derive_metrics(m)
    assert d["self_consumption_pct"] == 75.0
    assert d["self_sufficiency_pct"] == 75.0
    assert d["round_trip_efficiency_pct"] == 85.0
    assert set(d) <= set(DERIVED_METRICS)


def test_missing_inputs_omit_the_metric_not_zero():
    # No counters at day start ⇒ nothing derived (missing ≠ zero, §4).
    assert derive_metrics({}) == {}
    # Only PV present, export missing ⇒ self-consumption can't be computed.
    assert "self_consumption_pct" not in derive_metrics({"today_pv_wh": 5_000})


def test_zero_denominator_is_omitted():
    m = {
        "today_pv_wh": 0,
        "today_grid_export_wh": 0,
        "today_load_wh": 0,
        "today_grid_import_wh": 0,
        "today_batt_charge_wh": 0,
        "today_batt_discharge_wh": 0,
    }
    assert derive_metrics(m) == {}  # every denominator is 0


def test_self_consumption_caps_at_full_when_export_exceeds_pv():
    # Export can briefly exceed today's PV via rounding/counters; self-consumed clamps to ≥ 0.
    d = derive_metrics({"today_pv_wh": 1_000, "today_grid_export_wh": 1_500})
    assert d["self_consumption_pct"] == 0.0


def test_non_numeric_values_ignored():
    d = derive_metrics({"today_pv_wh": "n/a", "today_grid_export_wh": 100})
    assert "self_consumption_pct" not in d

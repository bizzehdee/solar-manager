"""Cost / savings / CO₂ / ROI / round-trip efficiency (plan.md §3; task T052)."""

from __future__ import annotations

from app import economics


def test_round_trip_efficiency():
    assert economics.round_trip_efficiency(1000.0, 900.0) == 0.9
    assert economics.round_trip_efficiency(0.0, 0.0) is None  # never charged


def test_self_consumed_pv():
    assert economics.self_consumed_pv_wh(10000, 3000) == 7000
    assert economics.self_consumed_pv_wh(1000, 2000) == 0  # clamped


def test_compute_economics_savings_and_co2():
    # Imported £2 worth, exported £0.50, baseline (all-grid) would've been £5.
    econ = economics.compute_economics(
        import_cost=2.0,
        export_revenue=0.5,
        baseline_cost=5.0,
        pv_wh=10000.0,      # 10 kWh generated
        export_wh=4000.0,   # 4 kWh exported -> 6 kWh self-consumed
        co2_intensity_g_per_kwh=200.0,
    )
    assert econ.net_cost == 1.5            # 2.0 - 0.5
    assert econ.savings == 3.5             # 5.0 - 1.5
    assert econ.co2_avoided_kg == 1.2      # 6 kWh * 200 g/kWh = 1200 g = 1.2 kg


def test_standing_charge_folds_into_net_and_baseline_but_cancels_in_savings():
    # Same flows as above, plus a 60.75p/day standing charge.
    econ = economics.compute_economics(
        import_cost=2.0,
        export_revenue=0.5,
        baseline_cost=5.0,
        pv_wh=10000.0,
        export_wh=4000.0,
        co2_intensity_g_per_kwh=200.0,
        standing_charge=0.6075,
    )
    assert econ.standing_charge == 0.6075
    assert econ.net_cost == 1.5 + 0.6075        # real bill includes the fixed charge
    assert econ.baseline_cost == 5.0 + 0.6075   # so does the no-solar baseline
    assert econ.savings == 3.5                  # …so solar savings are unchanged (it can't avoid it)
    assert econ.as_dict()["standing_charge"] == 0.6075


def test_standing_charge_defaults_to_zero():
    econ = economics.compute_economics(
        import_cost=2.0, export_revenue=0.5, baseline_cost=5.0,
        pv_wh=0.0, export_wh=0.0, co2_intensity_g_per_kwh=0.0,
    )
    assert econ.standing_charge == 0.0 and econ.net_cost == 1.5


def test_economics_as_dict_rounds():
    econ = economics.compute_economics(
        import_cost=1.23456, export_revenue=0.0, baseline_cost=2.0,
        pv_wh=0.0, export_wh=0.0, co2_intensity_g_per_kwh=0.0,
    )
    assert econ.as_dict()["import_cost"] == 1.2346


def test_payback_and_roi():
    assert economics.payback_years(5000.0, 1000.0) == 5.0
    assert economics.payback_years(5000.0, 0.0) is None        # never pays back
    assert economics.roi_percent(5000.0, 1000.0, 25.0) == 400.0  # (25k - 5k)/5k * 100
    assert economics.roi_percent(0.0, 1000.0, 25.0) is None

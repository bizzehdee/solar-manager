"""Tariff model: flat/TOU/seasonal rates + costing (plan.md §5; task T051)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.tariff import RateSchedule, Season, Tariff, TouWindow, hourly_deltas


def test_flat_schedule_rate():
    s = RateSchedule(flat=0.30)
    assert s.rate_at(3) == 0.30 and s.rate_at(18) == 0.30


def test_tou_window_lookup_and_fallback():
    night = TouWindow(start_hour=0, end_hour=7, rate=0.10)
    peak = TouWindow(start_hour=16, end_hour=19, rate=0.45)
    s = RateSchedule(flat=0.28, windows=(night, peak))
    assert s.rate_at(2) == 0.10      # in night window
    assert s.rate_at(17) == 0.45     # in peak window
    assert s.rate_at(12) == 0.28     # falls back to flat


def test_tou_window_wraps_midnight():
    w = TouWindow(start_hour=23, end_hour=6, rate=0.08)
    assert w.contains(23.5) and w.contains(0.0) and w.contains(5.9)
    assert not w.contains(6.0) and not w.contains(12.0)


def test_cost_of_deltas_uses_window_rate():
    s = RateSchedule(flat=0.30, windows=(TouWindow(0, 7, 0.10),))
    # 2 kWh at 02:00 (night, 0.10) + 1 kWh at 12:00 (flat 0.30) = 0.20 + 0.30
    cost = s.cost_of_deltas([(2.0, 2000.0), (12.0, 1000.0)])
    assert cost == 0.5


def test_seasonal_override_selected_by_month():
    summer = Season(4, 9, RateSchedule(flat=0.20), RateSchedule(flat=0.05))
    winter = Season(10, 3, RateSchedule(flat=0.40), RateSchedule(flat=0.15))
    t = Tariff(import_rate=RateSchedule(flat=0.30), seasons=(summer, winter))
    imp_jul, _ = t.schedules_for(datetime(2026, 7, 1, tzinfo=timezone.utc))
    imp_jan, _ = t.schedules_for(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert imp_jul.flat == 0.20   # summer
    assert imp_jan.flat == 0.40   # winter (wraps Oct→Mar)


def test_tariff_roundtrips_through_dict():
    t = Tariff(
        import_rate=RateSchedule(flat=0.28, windows=(TouWindow(0, 7, 0.10),)),
        export_rate=RateSchedule(flat=0.05),
        currency="EUR",
        seasons=(Season(11, 2, RateSchedule(flat=0.4), RateSchedule(flat=0.1)),),
    )
    again = Tariff.from_dict(t.to_dict())
    assert again.currency == "EUR"
    assert again.import_rate.rate_at(3) == 0.10
    assert again.import_rate.rate_at(12) == 0.28
    assert again.seasons[0].start_month == 11


def test_standing_charge_roundtrips():
    # The user's real tariff: 60.75p/day standing, TOU import (9p 00–06, 29.3p otherwise),
    # flat 17.5p export. Stored/loaded losslessly.
    t = Tariff(
        import_rate=RateSchedule(
            flat=0.293,
            windows=(TouWindow(0, 6, 0.09), TouWindow(6, 0, 0.293)),
        ),
        export_rate=RateSchedule(flat=0.175),
        currency="GBP",
        standing_charge=0.6075,
    )
    again = Tariff.from_dict(t.to_dict())
    assert again.standing_charge == 0.6075
    assert again.import_rate.rate_at(3) == 0.09     # overnight cheap rate
    assert again.import_rate.rate_at(18) == 0.293   # daytime rate
    assert again.export_rate.rate_at(12) == 0.175


def test_standing_charge_defaults_to_zero_when_absent():
    assert Tariff.from_dict({}).standing_charge == 0.0


def test_from_dict_accepts_bare_number_as_flat():
    assert RateSchedule.from_dict(0.25).flat == 0.25
    assert RateSchedule.from_dict(None).flat == 0.0


def test_hourly_deltas_from_counter_series():
    # cumulative counter (epoch at 00:00, 01:00, 02:00 UTC) -> per-hour deltas with hour.
    base = datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc).timestamp()
    series = [(base, 0.0), (base + 3600, 500.0), (base + 7200, 1200.0)]
    deltas = hourly_deltas(series)
    assert deltas == [(1.0, 500.0), (2.0, 700.0)]


def test_hourly_deltas_handles_reset():
    base = datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc).timestamp()
    series = [(base, 4000.0), (base + 3600, 50.0)]  # reset
    assert hourly_deltas(series) == [(1.0, 50.0)]

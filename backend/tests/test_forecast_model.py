"""PV generation model: solar position, transposition, thermal derate (task T061)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.forecast import model
from app.forecast.model import ArraySegment


def test_solar_elevation_positive_at_local_noon_negative_at_night():
    # London, summer solstice. ~12:00 UTC ≈ solar noon; 00:00 UTC is night.
    noon = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    night = datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc)
    el_noon, az_noon = model.solar_elevation_azimuth(51.5, -0.13, noon)
    el_night, _ = model.solar_elevation_azimuth(51.5, -0.13, night)
    assert el_noon > 55.0           # high midsummer sun
    assert el_night < 0.0           # below horizon
    assert 150 < az_noon < 210      # roughly due south at noon


def test_poa_equals_ghi_for_flat_panel():
    # With tilt=0 the isotropic model collapses to POA == GHI (beam+diffuse recombine).
    poa = model.poa_irradiance(500.0, elevation_deg=45.0, azimuth_deg=180.0,
                               tilt=0.0, panel_azimuth=180.0, day_of_year=172)
    assert poa == pytest.approx(500.0, rel=1e-6)


def test_poa_zero_at_night():
    assert model.poa_irradiance(0.0, -5.0, 180.0, 35.0, 180.0, 1) == 0.0
    assert model.poa_irradiance(300.0, -1.0, 180.0, 35.0, 180.0, 1) == 0.0


def test_cell_temperature_nmot_model():
    # At 800 W/m², cell sits (NMOT-20) above ambient: 25 + (41-20) = 46 °C.
    assert model.cell_temperature(800.0, 25.0, 41.0) == pytest.approx(46.0)
    assert model.cell_temperature(0.0, 15.0, 41.0) == 15.0  # no sun -> ambient


def test_segment_power_scales_with_kwp_and_derates_with_heat():
    common = dict(ghi=800.0, elevation_deg=50.0, azimuth_deg=180.0, day_of_year=172)
    s1 = ArraySegment("a", kwp=3.0, tilt=30, azimuth=180)
    s2 = ArraySegment("b", kwp=6.0, tilt=30, azimuth=180)
    p1 = model.segment_power_w(s1, air_temp_c=20.0, **common)
    p2 = model.segment_power_w(s2, air_temp_c=20.0, **common)
    assert p1 > 0
    assert p2 == pytest.approx(2 * p1, rel=1e-6)        # double kWp -> double power
    hot = model.segment_power_w(s1, air_temp_c=40.0, **common)
    assert hot < p1                                      # hotter -> less power (γ<0)


def test_expected_power_sums_segments_and_is_zero_at_night():
    segs = [ArraySegment("a", 3.0, 35, 135), ArraySegment("b", 3.0, 35, 225)]
    noon = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    midnight = datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc)
    assert model.expected_power_w(segs, 51.5, -0.13, noon, ghi=700.0, air_temp_c=20.0) > 0
    assert model.expected_power_w(segs, 51.5, -0.13, midnight, ghi=0.0, air_temp_c=10.0) == 0.0


def test_array_segment_from_dict_defaults():
    s = ArraySegment.from_dict({"kwp": 4.0})
    assert s.gamma_pmax == model.DEFAULT_GAMMA_PMAX and s.nmot == model.DEFAULT_NMOT
    assert s.tilt == 30.0 and s.azimuth == 180.0

"""DummyProfile synthesis (plan.md §4 dummy, §21)."""

from __future__ import annotations

from datetime import timedelta

from app.devices.dummy import DummyProfile, NullTransport
from app.metrics import ALL_METRICS, CORE_METRICS


def test_reports_full_core_vocabulary(midday):
    profile = DummyProfile(clock=lambda: midday)
    metrics = profile.synthesize(midday)
    assert CORE_METRICS <= set(metrics), "dummy must report the complete core set"


def test_capabilities_is_full_canonical_set():
    assert DummyProfile().capabilities() == set(ALL_METRICS)


def test_deterministic_for_same_timestamp(midday):
    a = DummyProfile(seed=7).synthesize(midday)
    b = DummyProfile(seed=7).synthesize(midday)
    assert a == b, "synthesis must be a pure function of (seed, timestamp)"


def test_midday_produces_pv_and_midnight_does_not(midday, midnight):
    profile = DummyProfile()
    assert profile.synthesize(midday)["pv_power_w"] > 0
    assert profile.synthesize(midnight)["pv_power_w"] == 0


def test_pv_total_is_sum_of_strings(midday):
    m = DummyProfile().synthesize(midday)
    assert abs(m["pv_power_w"] - (m["pv1_power_w"] + m["pv2_power_w"])) < 1.0


def test_soc_within_bounds():
    profile = DummyProfile()
    base = profile._clock()
    for minutes in range(0, 24 * 60, 37):
        ts = base + timedelta(minutes=minutes)
        soc = profile.synthesize(ts)["battery_soc_pct"]
        assert 0 <= soc <= 100


async def test_null_transport_is_inert():
    t = NullTransport()
    await t.connect()
    assert await t.read_registers(0, 4) == [0, 0, 0, 0]
    await t.write_registers(0, [1])  # no-op, no raise
    await t.close()

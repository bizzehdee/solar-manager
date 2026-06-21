"""Stats-based derived metrics + poller merge — task L16-2."""

from __future__ import annotations

from datetime import datetime, timezone

from app.derived_stats import STATS_DERIVED_METRICS, DerivedStatsService
from app.poller import Poller
from app.stats import DailyStats


class _FakeStats:
    """Stands in for StatsService.daily, returning a fixed DailyStats."""

    def __init__(self, **econ):
        self.econ = {"savings": 1.2345, "co2_avoided_kg": 0.6789, **econ}
        self.peak = 4321.7

    async def daily(self, device_id, day_start):
        return DailyStats(
            device_id=device_id, date="2026-06-21", energy_wh={},
            self_consumption_pct=75.0, self_sufficiency_pct=60.0,
            peak_pv_w=self.peak, round_trip_efficiency=0.9,
            economics=self.econ, currency="GBP",
        )


class _Dev:
    def __init__(self, device_id):
        self.device_id = device_id


class _Reg:
    def __init__(self, ids):
        self.devices = [_Dev(i) for i in ids]


def _clock():
    return datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


async def test_cache_exposes_rounded_stats_metrics():
    svc = DerivedStatsService(_FakeStats(), _Reg(["inv"]), clock=_clock)
    await svc.refresh_once()
    v = svc.values("inv")
    assert v == {"savings": 1.23, "co2_avoided_kg": 0.68, "peak_pv_w": 4322.0}
    assert set(v) <= set(STATS_DERIVED_METRICS)


async def test_peak_omitted_when_unknown():
    stats = _FakeStats()
    stats.peak = None  # no rollup yet → missing ≠ zero
    svc = DerivedStatsService(stats, _Reg(["inv"]), clock=_clock)
    await svc.refresh_once()
    assert "peak_pv_w" not in svc.values("inv")
    assert svc.values("inv")["savings"] == 1.23  # savings still present (0 is a real value)


async def test_unknown_device_has_empty_values():
    svc = DerivedStatsService(_FakeStats(), _Reg(["inv"]), clock=_clock)
    assert svc.values("nope") == {}


class _OneDeviceReg:
    devices = [_Dev("d1")]

    async def read_all(self):
        from app.models import Reading
        return [Reading(device_id="d1", ts=_clock(), metrics={"pv_power_w": 100.0})]


async def test_poller_merges_provider_values_into_readings():
    cache = {"d1": {"savings": 2.5, "peak_pv_w": 5000.0}}
    poller = Poller(_OneDeviceReg(), derived_provider=lambda dev: cache.get(dev, {}))
    await poller.poll_once()
    m = poller.snapshot()["devices"]["d1"]["metrics"]
    assert m["savings"] == 2.5 and m["peak_pv_w"] == 5000.0

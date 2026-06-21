"""Stats-based derived metrics — task L16-2.

Some derived metrics can't be computed from a single snapshot: savings and CO₂ need the day's
energy priced against the (possibly time-of-use) tariff, and peak PV is the day's max. Those are
exactly what `StatsService.daily` computes for the stats page, so this service reuses it — running
periodically **off the hot path** and caching today's values per device. The poller reads the cache
each poll (cheap) and merges the values into each `Reading`, so they appear in the live snapshot and
are persisted like any metric (and stay in lock-step with `/api/stats/daily`).

Pure snapshot-derived ratios (self-consumption %, …) are handled inline by `derived.derive_metrics`;
this only supplies the DB/stats-derived set.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from .devices.base import system_clock
from .devices.registry import DeviceRegistry
from .models import MetricValue
from .stats import StatsService

# Metric keys this service contributes (folded into metrics.ALL_METRICS via metrics.DERIVED_METRICS).
STATS_DERIVED_METRICS = ("savings", "co2_avoided_kg", "peak_pv_w")


class DerivedStatsService:
    def __init__(
        self,
        stats: StatsService,
        registry: DeviceRegistry,
        *,
        clock: Callable = system_clock,
        interval_s: float = 60.0,
    ) -> None:
        self._stats = stats
        self._registry = registry
        self._clock = clock
        self._interval = interval_s
        self._task: asyncio.Task | None = None
        self._cache: dict[str, dict[str, MetricValue]] = {}

    def values(self, device_id: str) -> dict[str, MetricValue]:
        """Today's cached stats-derived metrics for a device (empty until first refresh)."""
        return dict(self._cache.get(device_id, {}))

    async def refresh_once(self) -> None:
        now_ts = self._clock().timestamp()
        for device in self._registry.devices:
            try:
                ds = await self._stats.daily(device.device_id, now_ts)
            except Exception:  # never let a stats hiccup affect polling; keep the last cache
                continue
            out: dict[str, MetricValue] = {}
            econ = ds.economics or {}
            if isinstance(econ.get("savings"), (int, float)):
                out["savings"] = round(float(econ["savings"]), 2)
            if isinstance(econ.get("co2_avoided_kg"), (int, float)):
                out["co2_avoided_kg"] = round(float(econ["co2_avoided_kg"]), 2)
            if isinstance(ds.peak_pv_w, (int, float)):  # None until rollups exist (missing ≠ zero)
                out["peak_pv_w"] = round(float(ds.peak_pv_w), 0)
            self._cache[device.device_id] = out

    async def _run(self) -> None:
        while True:
            await self.refresh_once()
            await asyncio.sleep(self._interval)

    async def start(self) -> None:
        if self._task is None:
            await self.refresh_once()  # seed the cache before the first polls
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

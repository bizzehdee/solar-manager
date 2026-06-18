"""Grid-outage / backup-power detection (plan.md §19 / T095) — pure logic + a tiny service.

From the canonical metrics we infer whether the grid is present (`run_state` on/off-grid, or
grid voltage as a fallback) and log **outage start / end** events so hybrid/backup users get a
timeline of when they were islanded. Detection is a pure transition tracker (unit-tested); the
service just steps it off the poller snapshot each tick (off the hot path)."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

log = logging.getLogger("solarvolt.grid")

GridEvent = Literal["outage_start", "outage_end"]
_GRID_VOLTAGE_UP = 50.0  # V — below this (and no run_state) the grid is treated as absent


def grid_up(metrics: dict) -> bool | None:
    """Is the grid present? True/False, or None when the metrics don't say (missing ≠ down).
    Prefers the decoded `run_state` (on_grid/off_grid); falls back to grid voltage."""
    rs = metrics.get("run_state")
    if isinstance(rs, str):
        if rs == "on_grid":
            return True
        if rs == "off_grid":
            return False
    v = metrics.get("grid_voltage_v")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v > _GRID_VOLTAGE_UP
    return None


class GridEventDetector:
    """Tracks grid-up state per device and emits outage_start/outage_end on transitions."""

    def __init__(self) -> None:
        self._up: dict[str, bool] = {}

    def step(self, device_id: str, up: bool | None, ts: float) -> GridEvent | None:
        if up is None:
            return None  # unknown — never inferred as a transition
        prev = self._up.get(device_id)
        self._up[device_id] = up
        if prev is None or prev == up:
            return None
        return "outage_end" if up else "outage_start"


class GridEventService:
    """Background task: step the detector off the poller snapshot and log transitions."""

    def __init__(self, repo, poller, *, interval_s: float = 30.0, clock=None) -> None:
        import datetime as _dt

        self._repo = repo
        self._poller = poller
        self._interval = interval_s
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))
        self._detector = GridEventDetector()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.evaluate_once()
            except Exception as exc:  # never let detection crash the loop
                log.warning("Grid-event detection failed: %s", exc)
            await asyncio.sleep(self._interval)

    async def evaluate_once(self) -> list[GridEvent]:
        now = self._clock().timestamp()
        snapshot = self._poller.snapshot()
        events: list[GridEvent] = []
        for device_id, dev in snapshot.get("devices", {}).items():
            event = self._detector.step(device_id, grid_up(dev.get("metrics", {})), now)
            if event:
                await self._repo.insert_grid_event(now, device_id, event)
                events.append(event)
        return events

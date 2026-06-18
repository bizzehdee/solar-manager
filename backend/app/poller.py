"""Async poller (plan.md §4 architecture, §10).

Polls the device registry on an interval, keeps the latest snapshot, and broadcasts
each new snapshot to WebSocket subscribers. Poll cadence is decoupled from any
downstream consumer; a subscriber that can't keep up drops frames rather than
back-pressuring the poll loop.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .devices.registry import DeviceRegistry
from .models import Reading


class Poller:
    def __init__(self, registry: DeviceRegistry, interval_s: float = 3.0) -> None:
        self._registry = registry
        self._interval = interval_s
        self._task: asyncio.Task | None = None
        self._latest: dict[str, Reading] = {}
        self._subscribers: set[asyncio.Queue] = set()

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
            await self.poll_once()
            await asyncio.sleep(self._interval)

    async def poll_once(self) -> list[Reading]:
        readings = await self._registry.read_all()
        for r in readings:
            self._latest[r.device_id] = r
        self._broadcast()
        return readings

    def latest_readings(self) -> list[Reading]:
        """The most recent Reading per device (consumed by the persistence service)."""
        return list(self._latest.values())

    async def ensure_polled(self) -> None:
        """Guarantee at least one snapshot exists (used by request handlers/tests so a
        fresh process serves data immediately rather than after the first interval)."""
        if not self._latest:
            await self.poll_once()

    # --- snapshots + subscriptions ---------------------------------------------
    def snapshot(self) -> dict:
        return {
            "ts": _now_iso(),
            "devices": {
                device_id: {
                    "ts": reading.ts.isoformat(),
                    "metrics": reading.metrics,
                }
                for device_id, reading in self._latest.items()
            },
        }

    def health(self) -> dict:
        now = datetime.now(timezone.utc)
        devices = []
        for device in self._registry.devices:
            reading = self._latest.get(device.device_id)
            age = None
            if reading is not None:
                age = (now - reading.ts.astimezone(timezone.utc)).total_seconds()
            devices.append(
                {
                    "device_id": device.device_id,
                    "vendor": device.info.vendor,
                    "model": device.info.model,
                    "online": reading is not None,
                    "last_sample_age_s": age,
                }
            )
        return {"devices": devices, "poll_interval_s": self._interval}

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _broadcast(self) -> None:
        snap = self.snapshot()
        for q in list(self._subscribers):
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                pass  # slow consumer drops frames; never block the poll loop


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

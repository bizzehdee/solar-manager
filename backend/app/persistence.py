"""Persistence service (plan.md §5, §10; tasks T042/T043).

Bridges the live poller to the history repository on its **own** cadence, decoupled from
the poll rate (plan.md §10): the poller may read every few seconds for a responsive Now
view, while we persist a sample less often to keep the DB compact. Periodically it also
rolls raw samples up (5m/1h/1d) and prunes raw past the retention window.

A failing DB write degrades to a logged warning — it never blocks or crashes the poll
loop (egress/persistence is off the hot path).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .poller import Poller
from .storage.repository import SqliteHistoryRepository

log = logging.getLogger("solarvolt.persistence")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PersistenceService:
    def __init__(
        self,
        repo: SqliteHistoryRepository,
        poller: Poller,
        *,
        persist_interval_s: float = 30.0,
        aggregate_interval_s: float = 300.0,
        retention_days: float = 14.0,
        clock=_utcnow,
    ) -> None:
        self._repo = repo
        self._poller = poller
        self._persist_interval = persist_interval_s
        self._aggregate_interval = aggregate_interval_s
        self._retention_s = retention_days * 86400.0
        self._clock = clock
        self._task: asyncio.Task | None = None
        self._last_persisted_ts: dict[str, float] = {}

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
        elapsed = 0.0
        while True:
            await self.persist_once()
            elapsed += self._persist_interval
            if elapsed >= self._aggregate_interval:
                elapsed = 0.0
                await self.maintain_once()
            await asyncio.sleep(self._persist_interval)

    async def persist_once(self) -> int:
        """Persist each device's latest reading, skipping ones we've already stored
        (same timestamp) so a slow persist cadence doesn't duplicate rows."""
        stored = 0
        for reading in self._poller.latest_readings():
            ts = reading.ts.timestamp()
            if self._last_persisted_ts.get(reading.device_id) == ts:
                continue
            try:
                stored += await self._repo.write_reading(reading)
                self._last_persisted_ts[reading.device_id] = ts
            except Exception as exc:  # never let a DB hiccup kill the loop
                log.warning("Failed to persist reading for %s: %s", reading.device_id, exc)
        return stored

    async def maintain_once(self) -> None:
        """Roll up raw → buckets, then prune raw past the retention window (in that
        order, so the rollups already hold everything before raw is deleted)."""
        try:
            await self._repo.aggregate()
            cutoff = self._clock().timestamp() - self._retention_s
            await self._repo.prune(cutoff)
        except Exception as exc:
            log.warning("Rollup/prune maintenance failed: %s", exc)

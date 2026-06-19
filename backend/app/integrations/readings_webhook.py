"""Generic outbound readings webhook (plan.md §14; task L09).

Periodically POSTs the latest normalized snapshot to a user-supplied URL (Node-RED / IFTTT /
custom). This is the *readings stream* — alert egress is already covered by the Phase-7
webhook **channel** (`app.alerts.channels`). Like the persistence and alert services it runs
as its own background task on its own cadence; a dead endpoint is logged and swallowed so it
can never disrupt the poll loop (egress is off the hot path).

Config lives in the `readings_webhook` app-config blob and is re-read every tick, so edits in
Settings apply on the next cycle with no restart:
    {"url": "http://…", "interval_s": 60.0, "enabled": true}

The HTTP call is injectable so tests run with no network.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger("solarvolt.integrations")

# post(url, json) -> None. Injected so tests don't hit the network.
Post = Callable[[str, dict], Awaitable[None]]

# Never POST faster than this, whatever the configured interval, to protect the host.
MIN_INTERVAL_S = 5.0
DEFAULT_INTERVAL_S = 60.0


async def _httpx_post(url: str, payload: dict) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


class ReadingsWebhookService:
    def __init__(
        self,
        poller,
        app_config,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        post: Post | None = None,
    ) -> None:
        self._poller = poller
        self._app_config = app_config
        self._interval = interval_s
        self._post = post or _httpx_post
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
            interval = await self._tick()
            await asyncio.sleep(interval)

    async def _tick(self) -> float:
        """Read the live config, POST when enabled+configured, return the next sleep length.
        Any failure is logged and swallowed — egress must never disrupt the loop."""
        cfg = await self._app_config.get("readings_webhook", {}) or {}
        interval = max(float(cfg.get("interval_s") or self._interval), MIN_INTERVAL_S)
        url = cfg.get("url")
        if cfg.get("enabled") and url:
            try:
                await self.post_once(url)
            except Exception as exc:  # a dead endpoint must not disrupt the loop
                log.warning("Readings webhook POST to %r failed: %s", url, exc)
        return interval

    async def post_once(self, url: str) -> bool:
        """POST the current snapshot once. Returns False (without POSTing) when there is no
        reading yet — there's nothing to send. Raises on transport failure (callers in the
        loop swallow it; the manual test endpoint surfaces it)."""
        snapshot = self._poller.snapshot()
        if not snapshot.get("devices"):
            return False
        await self._post(url, {"type": "readings", **snapshot})
        return True

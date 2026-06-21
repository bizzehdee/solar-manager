"""Generic outbound readings webhooks (plan.md §14; tasks L09, L15).

Periodically POSTs the latest normalized snapshot to **any number of** user-supplied endpoints
(Node-RED / IFTTT / Slack / custom), each with its own URL, headers, content-type, payload
template and cadence. This is the *readings stream* — alert egress is the Phase-7 webhook
**channels** (`app.alerts.channels`). Like persistence/alerts it runs as one background task; a
dead endpoint is logged and swallowed so it can never disrupt the poll loop (egress is off the
hot path).

Config is the `readings_webhooks` app-config list, re-read every tick so Settings edits apply
with no restart. Each entry::

    {"id": "nodered", "label": "Node-RED", "url": "http://…", "method": "POST",
     "headers": {...}, "content_type": "application/json", "payload_template": "",
     "interval_s": 60.0, "enabled": true}

An empty template sends the full snapshot as JSON (the legacy body). The HTTP call is injectable
so tests run with no network.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from ..templating import render_body

log = logging.getLogger("solarvolt.integrations")

# post(url, *, body, headers, method) -> None. Injected so tests don't hit the network.
Post = Callable[..., Awaitable[None]]

# Never POST faster than this per endpoint, whatever the configured interval, to protect the host.
MIN_INTERVAL_S = 5.0
DEFAULT_INTERVAL_S = 60.0


async def _httpx_post(url: str, *, body: str, headers: dict | None = None, method: str = "POST") -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.request(method, url, content=body.encode("utf-8"), headers=headers)
        resp.raise_for_status()


def readings_context(snapshot: dict) -> dict[str, Any]:
    """Flatten a snapshot into placeholder values: ``ts`` plus ``{device}_{metric}`` for every
    metric, and bare ``{metric}`` keys for the first device's convenience."""
    ctx: dict[str, Any] = {"ts": snapshot.get("ts")}
    for i, (dev_id, dev) in enumerate(snapshot.get("devices", {}).items()):
        for key, value in (dev.get("metrics") or {}).items():
            ctx[f"{dev_id}_{key}"] = value
            if i == 0:
                ctx.setdefault(key, value)
    return ctx


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
        self._last_sent: dict[str, float] = {}  # endpoint id → last POST epoch

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
        """POST each enabled endpoint that's due, and return how long to sleep until the next one
        is due (bounded so config edits are picked up promptly). Failures are logged, not raised."""
        endpoints = await self._app_config.get("readings_webhooks", []) or []
        now = time.monotonic()
        soonest: float | None = None
        for ep in endpoints:
            if not (ep.get("enabled") and ep.get("url")):
                continue
            interval = max(float(ep.get("interval_s") or self._interval), MIN_INTERVAL_S)
            eid = ep.get("id") or ep["url"]
            due_in = interval - (now - self._last_sent.get(eid, 0.0))
            if due_in <= 0:
                self._last_sent[eid] = now
                try:
                    await self.post_once(ep)
                except Exception as exc:  # a dead endpoint must not disrupt the loop
                    log.warning("Readings webhook POST to %r failed: %s", ep.get("url"), exc)
                due_in = interval
            soonest = due_in if soonest is None else min(soonest, due_in)
        # Re-check at least every `interval` so config edits apply without a restart.
        return min(soonest if soonest is not None else self._interval, self._interval)

    async def post_once(self, endpoint: dict) -> bool:
        """POST the current snapshot once to one endpoint. Returns False (without POSTing) when
        there's no reading yet. Raises on transport failure (the loop swallows it; the manual
        test endpoint surfaces it)."""
        snapshot = self._poller.snapshot()
        if not snapshot.get("devices"):
            return False
        content_type = endpoint.get("content_type") or "application/json"
        body = render_body(
            endpoint.get("payload_template"),
            readings_context(snapshot),
            {"type": "readings", **snapshot},
            json_escape=content_type.startswith("application/json"),
        )
        headers = dict(endpoint.get("headers") or {})
        headers.setdefault("Content-Type", content_type)
        await self._post(endpoint["url"], body=body, headers=headers,
                         method=(endpoint.get("method") or "POST").upper())
        return True

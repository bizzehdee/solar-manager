"""Notification channels (plan.md §15) — pluggable, like transports. Every fired alert is
always recorded in the in-app inbox (the DB); channels are *additional* push delivery.

Off the hot path: a channel failure is logged and swallowed, never raised, so a dead
webhook/SMTP host can't disrupt the alert loop. A generic **webhook** (HTTP POST) ships;
ntfy/Telegram/Pushover/email are webhook-shaped and slot in here later behind the same
protocol. The HTTP call is injectable so tests run with no network.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol

log = logging.getLogger("solarvolt.alerts")

# post(url, json) -> None. Injected so tests don't hit the network.
Post = Callable[[str, dict], Awaitable[None]]


async def _httpx_post(url: str, payload: dict) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


class Channel(Protocol):
    name: str

    async def send(self, alert: dict) -> None: ...


class WebhookChannel:
    """POST the alert payload to a user URL (Node-RED / IFTTT / ntfy / custom)."""

    name = "webhook"

    def __init__(self, url: str, *, post: Post | None = None) -> None:
        self._url = url
        self._post = post or _httpx_post

    async def send(self, alert: dict) -> None:
        await self._post(self._url, alert)


def build_channels(config: dict, *, post: Post | None = None) -> dict[str, Channel]:
    """Build the configured channels from the `alert_channels` app-config blob, e.g.
    `{"webhook": {"url": "http://..."}}`. Unknown/incomplete entries are skipped."""
    channels: dict[str, Channel] = {}
    wh = (config or {}).get("webhook") or {}
    if wh.get("url"):
        channels["webhook"] = WebhookChannel(wh["url"], post=post)
    return channels


async def dispatch(channels: dict[str, Channel], names: tuple[str, ...] | list[str], alert: dict) -> None:
    """Deliver one alert to the selected channels. Each failure is logged, never raised —
    egress is off the hot path (plan.md §14/§15)."""
    for name in names:
        channel = channels.get(name)
        if channel is None:
            continue
        try:
            await channel.send(alert)
        except Exception as exc:  # a dead channel must not disrupt alerting
            log.warning("Alert channel %r failed: %s", name, exc)

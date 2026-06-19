"""Notification channels (plan.md §15) — pluggable, like transports. Every fired alert is
always recorded in the in-app inbox (the DB); channels are *additional* push delivery.

Off the hot path: a channel failure is logged and swallowed, never raised, so a dead
host can't disrupt the alert loop. The shipped channels (task L10) are all "webhook-shaped"
HTTP POSTs — **webhook** (generic), **Telegram**, **ntfy**, **Gotify**, **Pushover** — plus
**email** over SMTP. They slot in behind one `Channel` protocol and are selectable per rule.

Both side effects are injected so tests run with no network and no mail server:
`post` for the HTTP channels, `send_email` for SMTP.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Protocol

log = logging.getLogger("solarvolt.alerts")

# post(url, json=…, data=…, headers=…) -> None. JSON by default; `data` is form-encoded
# (Pushover wants a form). Injected so tests don't hit the network. The legacy 2-positional
# form `post(url, payload)` still works (WebhookChannel and existing callers rely on it).
Post = Callable[..., Awaitable[None]]
# send_email(cfg, subject, body) -> None (blocking smtplib; run off the loop via a thread).
SendEmail = Callable[[dict, str, str], None]

# Channel types we know how to build (drives the config UI + the rule-editor channel list).
SUPPORTED_CHANNELS = ("webhook", "email", "telegram", "ntfy", "gotify", "pushover")


async def _httpx_post(url: str, payload: dict | None = None, *, data: dict | None = None,
                      headers: dict | None = None) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, data=data, headers=headers)
        resp.raise_for_status()


def _smtp_send(cfg: dict, subject: str, body: str) -> None:
    """Blocking SMTP send (called via asyncio.to_thread). Stdlib only — no new dependency."""
    import smtplib
    from email.message import EmailMessage

    sender = cfg.get("from") or cfg.get("username") or "solarvolt@localhost"
    to = cfg.get("to")
    recipients = to if isinstance(to, list) else [to]
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(r for r in recipients if r)
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587)), timeout=10) as s:
        if cfg.get("use_tls", True):
            s.starttls()
        if cfg.get("username"):
            s.login(cfg["username"], cfg.get("password", ""))
        s.send_message(msg)


# Per-severity priority mapped into each provider's own scale.
def _priority(severity: str, scale: dict[str, int]) -> int:
    return scale.get(severity, scale["warning"])


def format_alert(alert: dict) -> tuple[str, str]:
    """Render an alert dict into a (title, body) pair shared by the push channels."""
    sev = str(alert.get("severity", "info"))
    name = alert.get("name") or alert.get("message") or alert.get("rule_id") or "Alert"
    title = f"[{sev.upper()}] {name}"
    parts: list[str] = []
    message = alert.get("message")
    if message and message != name:
        parts.append(str(message))
    metric = alert.get("metric")
    if metric:
        value = alert.get("value")
        parts.append(f"{metric} = {value}" if value is not None else str(metric))
    device = alert.get("device_id")
    if device:
        parts.append(f"device: {device}")
    return title, ("\n".join(parts) or name)


class Channel(Protocol):
    name: str

    async def send(self, alert: dict) -> None: ...


class WebhookChannel:
    """POST the raw alert payload to a user URL (Node-RED / IFTTT / custom)."""

    name = "webhook"

    def __init__(self, url: str, *, post: Post | None = None) -> None:
        self._url = url
        self._post = post or _httpx_post

    async def send(self, alert: dict) -> None:
        await self._post(self._url, alert)


class TelegramChannel:
    """Send a message via the Telegram Bot API."""

    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str, *, post: Post | None = None) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._post = post or _httpx_post

    async def send(self, alert: dict) -> None:
        title, body = format_alert(alert)
        await self._post(self._url, {"chat_id": self._chat_id, "text": f"{title}\n{body}"})


class NtfyChannel:
    """Publish to an ntfy topic (default the public ntfy.sh; self-hosted via `server`)."""

    name = "ntfy"
    _PRIORITY = {"info": 2, "warning": 3, "critical": 5}

    def __init__(self, topic: str, *, server: str = "https://ntfy.sh", post: Post | None = None) -> None:
        self._server = server.rstrip("/")
        self._topic = topic
        self._post = post or _httpx_post

    async def send(self, alert: dict) -> None:
        title, body = format_alert(alert)
        await self._post(self._server, {
            "topic": self._topic,
            "title": title,
            "message": body,
            "priority": _priority(str(alert.get("severity", "info")), self._PRIORITY),
        })


class GotifyChannel:
    """Push to a self-hosted Gotify server (application token)."""

    name = "gotify"
    _PRIORITY = {"info": 2, "warning": 5, "critical": 8}

    def __init__(self, url: str, token: str, *, post: Post | None = None) -> None:
        self._url = f"{url.rstrip('/')}/message?token={token}"
        self._post = post or _httpx_post

    async def send(self, alert: dict) -> None:
        title, body = format_alert(alert)
        await self._post(self._url, {
            "title": title,
            "message": body,
            "priority": _priority(str(alert.get("severity", "info")), self._PRIORITY),
        })


class PushoverChannel:
    """Send via Pushover (form-encoded, per their API)."""

    name = "pushover"
    _PRIORITY = {"info": -1, "warning": 0, "critical": 1}

    def __init__(self, token: str, user: str, *, post: Post | None = None) -> None:
        self._token = token
        self._user = user
        self._post = post or _httpx_post

    async def send(self, alert: dict) -> None:
        title, body = format_alert(alert)
        await self._post("https://api.pushover.net/1/messages.json", data={
            "token": self._token,
            "user": self._user,
            "title": title,
            "message": body,
            "priority": _priority(str(alert.get("severity", "info")), self._PRIORITY),
        })


class EmailChannel:
    """Email the alert over SMTP (stdlib smtplib, run off the event loop in a thread)."""

    name = "email"

    def __init__(self, cfg: dict, *, send_email: SendEmail | None = None) -> None:
        self._cfg = cfg
        self._send = send_email or _smtp_send

    async def send(self, alert: dict) -> None:
        title, body = format_alert(alert)
        await asyncio.to_thread(self._send, self._cfg, title, body)


def build_channels(config: dict, *, post: Post | None = None, send_email: SendEmail | None = None) -> dict[str, Channel]:
    """Build the configured channels from the `alert_channels` app-config blob. Each entry is
    only built when its required fields are present, so a half-filled config enables nothing.
    Example: `{"telegram": {"bot_token": "…", "chat_id": "…"}, "ntfy": {"topic": "alerts"}}`."""
    config = config or {}
    channels: dict[str, Channel] = {}

    wh = config.get("webhook") or {}
    if wh.get("url"):
        channels["webhook"] = WebhookChannel(wh["url"], post=post)

    tg = config.get("telegram") or {}
    if tg.get("bot_token") and tg.get("chat_id"):
        channels["telegram"] = TelegramChannel(tg["bot_token"], str(tg["chat_id"]), post=post)

    nt = config.get("ntfy") or {}
    if nt.get("topic"):
        channels["ntfy"] = NtfyChannel(nt["topic"], server=nt.get("server") or "https://ntfy.sh", post=post)

    go = config.get("gotify") or {}
    if go.get("url") and go.get("token"):
        channels["gotify"] = GotifyChannel(go["url"], go["token"], post=post)

    po = config.get("pushover") or {}
    if po.get("token") and po.get("user"):
        channels["pushover"] = PushoverChannel(po["token"], po["user"], post=post)

    em = config.get("email") or {}
    if em.get("host") and em.get("to"):
        channels["email"] = EmailChannel(em, send_email=send_email)

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

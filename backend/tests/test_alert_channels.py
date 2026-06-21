"""Notification channels: build from config, and dispatch that swallows failures (§14/§15)."""

from __future__ import annotations

import pytest

from app.alerts.channels import (
    EmailChannel,
    GotifyChannel,
    NtfyChannel,
    PushoverChannel,
    TelegramChannel,
    WebhookChannel,
    build_channels,
    dispatch,
    format_alert,
)


def _recorder():
    """An injectable post that records JSON and form calls uniformly."""
    calls: list[dict] = []

    async def post(url, payload=None, *, data=None, headers=None, body=None, method="POST"):
        calls.append({"url": url, "json": payload, "data": data, "headers": headers,
                      "body": body, "method": method})

    return calls, post


def test_build_channels_from_config():
    # Custom webhooks are a list; each enabled, addressed endpoint becomes `webhook:<id>`.
    chans = build_channels({"webhooks": [{"id": "h", "url": "http://h", "enabled": True}]})
    assert "webhook:h" in chans
    # No url, disabled, or empty list ⇒ no channel built.
    assert build_channels({"webhooks": [{"id": "h"}]}) == {}
    assert build_channels({"webhooks": [{"id": "h", "url": "http://h", "enabled": False}]}) == {}
    assert build_channels({}) == {}


def test_build_channels_only_enables_complete_configs():
    cfg = {
        "telegram": {"bot_token": "T", "chat_id": "42"},
        "ntfy": {"topic": "alerts"},
        "gotify": {"url": "http://g", "token": "G"},
        "pushover": {"token": "P", "user": "U"},
        "email": {"host": "mail", "to": "me@h"},
        # incomplete webhook (no url) → skipped:
        "webhooks": [{"id": "x"}],
    }
    chans = build_channels(cfg)
    assert set(chans) == {"telegram", "ntfy", "gotify", "pushover", "email"}
    # Missing required fields drop the channel.
    assert "telegram" not in build_channels({"telegram": {"bot_token": "T"}})
    assert "pushover" not in build_channels({"pushover": {"token": "P"}})


def test_format_alert_builds_title_and_body():
    title, body = format_alert(
        {"severity": "critical", "name": "Low SoC", "message": "Battery low",
         "metric": "battery_soc_pct", "value": 12, "device_id": "dummy"}
    )
    assert title == "[CRITICAL] Low SoC"
    assert "Battery low" in body and "battery_soc_pct = 12" in body and "device: dummy" in body


async def test_telegram_posts_chat_message():
    calls, post = _recorder()
    await TelegramChannel("TOK", "999", post=post).send({"severity": "warning", "name": "Hot"})
    assert calls[0]["url"] == "https://api.telegram.org/botTOK/sendMessage"
    assert calls[0]["json"]["chat_id"] == "999"
    assert "Hot" in calls[0]["json"]["text"]


async def test_ntfy_posts_topic_with_priority():
    calls, post = _recorder()
    await NtfyChannel("alerts", server="https://ntfy.example/", post=post).send({"severity": "critical", "name": "X"})
    assert calls[0]["url"] == "https://ntfy.example"  # trailing slash trimmed
    assert calls[0]["json"]["topic"] == "alerts" and calls[0]["json"]["priority"] == 5


async def test_gotify_targets_message_endpoint_with_token():
    calls, post = _recorder()
    await GotifyChannel("http://g/", "APPTOK", post=post).send({"severity": "info", "name": "X"})
    assert calls[0]["url"] == "http://g/message?token=APPTOK"
    assert calls[0]["json"]["priority"] == 2


async def test_pushover_sends_form_data():
    calls, post = _recorder()
    await PushoverChannel("TOK", "USR", post=post).send({"severity": "warning", "name": "X"})
    assert calls[0]["url"] == "https://api.pushover.net/1/messages.json"
    assert calls[0]["json"] is None and calls[0]["data"]["token"] == "TOK"
    assert calls[0]["data"]["user"] == "USR" and calls[0]["data"]["priority"] == 0


def test_smtp_send_builds_message_and_logs_in(monkeypatch):
    import smtplib

    from app.alerts import channels as ch

    captured: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            captured["host"], captured["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            captured["tls"] = True

        def login(self, user, pw):
            captured["login"] = (user, pw)

        def send_message(self, msg):
            captured["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    ch._smtp_send(
        {"host": "mail", "port": 2525, "username": "u", "password": "p", "to": ["a@h", "b@h"]},
        "Subject here", "Body here",
    )
    assert captured["host"] == "mail" and captured["port"] == 2525
    assert captured["tls"] is True and captured["login"] == ("u", "p")
    assert captured["msg"]["To"] == "a@h, b@h" and captured["msg"]["Subject"] == "Subject here"
    assert captured["msg"]["From"] == "u"  # falls back to username when `from` absent


async def test_email_channel_invokes_sender_off_the_loop():
    sent: list = []

    def fake_send(cfg, subject, body):
        sent.append((cfg, subject, body))

    await EmailChannel({"host": "mail", "to": "me@h"}, send_email=fake_send).send(
        {"severity": "info", "name": "Hello"}
    )
    assert sent and sent[0][1] == "[INFO] Hello"


async def test_webhook_default_body_is_the_raw_alert_json():
    import json
    calls, post = _recorder()
    await WebhookChannel({"id": "h", "url": "http://h"}, post=post).send({"rule_id": "r", "severity": "info"})
    assert calls[0]["url"] == "http://h" and calls[0]["method"] == "POST"
    assert json.loads(calls[0]["body"]) == {"rule_id": "r", "severity": "info"}
    assert calls[0]["headers"]["Content-Type"] == "application/json"


async def test_webhook_custom_template_renders_and_escapes():
    import json
    calls, post = _recorder()
    ep = {"id": "slack", "url": "http://slack", "method": "post",
          "payload_template": '{"text": "Alert: {name}"}', "headers": {"X-Token": "t"}}
    await WebhookChannel(ep, post=post).send({"name": 'say "hi"', "severity": "warning"})
    assert calls[0]["method"] == "POST"  # normalised
    assert calls[0]["headers"]["X-Token"] == "t"
    assert json.loads(calls[0]["body"]) == {"text": 'Alert: say "hi"'}


async def test_dispatch_delivers_to_selected_channels():
    calls, post = _recorder()
    chans = {"webhook:h": WebhookChannel({"id": "h", "url": "http://h"}, post=post)}
    await dispatch(chans, ["webhook:h"], {"rule_id": "r"})
    assert calls and calls[0]["url"] == "http://h"


async def test_dispatch_ignores_unknown_channel():
    await dispatch({}, ["nope"], {"rule_id": "r"})  # no raise


async def test_dispatch_swallows_channel_failure():
    async def boom(url, **kw):
        raise RuntimeError("dead host")

    chans = {"webhook:h": WebhookChannel({"id": "h", "url": "http://h"}, post=boom)}
    # A failing channel must NOT propagate (egress off the hot path).
    await dispatch(chans, ["webhook:h"], {"rule_id": "r"})

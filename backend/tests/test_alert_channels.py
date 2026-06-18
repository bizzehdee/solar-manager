"""Notification channels: build from config, and dispatch that swallows failures (§14/§15)."""

from __future__ import annotations

import pytest

from app.alerts.channels import WebhookChannel, build_channels, dispatch


def test_build_channels_from_config():
    sent: list = []
    chans = build_channels({"webhook": {"url": "http://h"}}, post=lambda u, p: sent.append((u, p)))
    assert "webhook" in chans
    # No url ⇒ no channel built.
    assert build_channels({"webhook": {}}) == {}
    assert build_channels({}) == {}


async def test_dispatch_delivers_to_selected_channels():
    sent: list = []

    async def post(url, payload):
        sent.append((url, payload))

    chans = {"webhook": WebhookChannel("http://h", post=post)}
    await dispatch(chans, ["webhook"], {"rule_id": "r"})
    assert sent == [("http://h", {"rule_id": "r"})]


async def test_dispatch_ignores_unknown_channel():
    await dispatch({}, ["nope"], {"rule_id": "r"})  # no raise


async def test_dispatch_swallows_channel_failure():
    async def boom(url, payload):
        raise RuntimeError("dead host")

    chans = {"webhook": WebhookChannel("http://h", post=boom)}
    # A failing channel must NOT propagate (egress off the hot path).
    await dispatch(chans, ["webhook"], {"rule_id": "r"})

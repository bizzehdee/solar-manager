"""Outbound readings webhook (L09): the off-hot-path service + its config/test API.

The HTTP POST is injected so nothing here touches the network.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.integrations import ReadingsWebhookService
from app.main import create_app

_BASE = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


class _Poller:
    """Minimal poller stand-in exposing just the snapshot() the service consumes."""

    def __init__(self, snapshot: dict) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> dict:
        return self._snapshot


class _Config:
    """In-memory AppConfig stand-in (get/set on a dict)."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    async def get(self, key: str, default=None):
        return self._data.get(key, default)

    async def set(self, key: str, value) -> None:
        self._data[key] = value


def _recorder():
    sent: list[tuple[str, str]] = []

    async def post(url: str, *, body: str, headers=None, method="POST") -> None:
        sent.append((url, body))

    return sent, post


_SNAP = {"ts": "2026-06-21T12:00:00+00:00",
         "devices": {"dummy": {"ts": "2026-06-21T12:00:00+00:00", "metrics": {"battery_soc_pct": 55.0}}}}


@pytest.mark.asyncio
async def test_post_once_sends_tagged_snapshot():
    sent, post = _recorder()
    svc = ReadingsWebhookService(_Poller(_SNAP), _Config(), post=post)
    assert await svc.post_once({"id": "h", "url": "http://hook"}) is True
    url, body = sent[0]
    payload = json.loads(body)
    assert url == "http://hook"
    assert payload["type"] == "readings"
    assert payload["devices"]["dummy"]["metrics"]["battery_soc_pct"] == 55.0


@pytest.mark.asyncio
async def test_post_once_with_template_renders_flattened_metrics():
    sent, post = _recorder()
    svc = ReadingsWebhookService(_Poller(_SNAP), _Config(), post=post)
    # Both the bare (first-device) key and the device-prefixed key resolve.
    ep = {"id": "h", "url": "http://hook",
          "payload_template": '{"soc": {battery_soc_pct}, "soc2": {dummy_battery_soc_pct}}'}
    assert await svc.post_once(ep) is True
    assert json.loads(sent[0][1]) == {"soc": 55.0, "soc2": 55.0}


@pytest.mark.asyncio
async def test_post_once_skips_when_no_reading_yet():
    sent, post = _recorder()
    svc = ReadingsWebhookService(_Poller({"ts": "…", "devices": {}}), _Config(), post=post)
    assert await svc.post_once({"id": "h", "url": "http://hook"}) is False
    assert sent == []


@pytest.mark.asyncio
async def test_tick_posts_only_when_enabled_and_configured():
    sent, post = _recorder()
    cfg = _Config({"readings_webhooks": [{"id": "h", "url": "http://hook", "enabled": False, "interval_s": 30}]})
    svc = ReadingsWebhookService(_Poller(_SNAP), cfg, post=post)

    # Disabled → no POST; sleep falls back to the default cap (nothing due).
    assert await svc._tick() == 60.0
    assert sent == []

    # Enabled → POSTs on the next due tick.
    cfg._data["readings_webhooks"][0]["enabled"] = True
    await svc._tick()
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_tick_clamps_interval_and_swallows_failures():
    async def boom(url: str, *, body: str, headers=None, method="POST") -> None:
        raise RuntimeError("dead endpoint")

    cfg = _Config({"readings_webhooks": [{"id": "h", "url": "http://hook", "enabled": True, "interval_s": 1}]})
    svc = ReadingsWebhookService(_Poller(_SNAP), cfg, post=boom)
    # interval clamped up to the 5s floor; the POST failure is swallowed (no raise).
    assert await svc._tick() == 5.0


@pytest.mark.asyncio
async def test_start_stop_is_clean():
    svc = ReadingsWebhookService(_Poller(_SNAP), _Config(), post=_recorder()[1])
    await svc.start()
    await svc.stop()  # cancels cleanly, no error


# --- API surface ---------------------------------------------------------------

def _client() -> TestClient:
    settings = Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600)
    return TestClient(create_app(settings=settings, clock=lambda: _BASE))


def test_readings_webhooks_config_round_trip_and_clamp():
    with _client() as client:
        # Default: nothing configured.
        assert client.get("/api/integrations/readings-webhooks").json() == {"webhooks": []}
        # Save: id slugified, interval clamped to the floor, URL trimmed.
        saved = client.put("/api/integrations/readings-webhooks", json={"webhooks": [
            {"id": "Node RED", "label": "Node-RED", "url": "  http://hook  ", "interval_s": 1, "enabled": True},
        ]}).json()
        wh = saved["webhooks"][0]
        assert wh["id"] == "node-red" and wh["label"] == "Node-RED"
        assert wh["url"] == "http://hook" and wh["interval_s"] == 5.0 and wh["enabled"] is True
        # Persisted.
        assert client.get("/api/integrations/readings-webhooks").json()["webhooks"][0]["url"] == "http://hook"


def test_readings_webhook_test_endpoint():
    with _client() as client:
        # Unknown id → 400.
        assert client.post("/api/integrations/readings-webhooks/nope/test").status_code == 400

        client.put("/api/integrations/readings-webhooks", json={"webhooks": [
            {"id": "hook", "url": "http://hook", "enabled": True}]})
        sent, post = _recorder()
        client.app.state.readings_webhook._post = post
        body = client.post("/api/integrations/readings-webhooks/hook/test").json()
        assert body == {"ok": True, "sent": True}
        assert sent and sent[0][0] == "http://hook"


def test_readings_webhook_test_endpoint_surfaces_failure():
    with _client() as client:
        client.put("/api/integrations/readings-webhooks", json={"webhooks": [
            {"id": "hook", "url": "http://hook", "enabled": True}]})

        async def boom(url: str, *, body: str, headers=None, method="POST") -> None:
            raise RuntimeError("connection refused")

        client.app.state.readings_webhook._post = boom
        assert client.post("/api/integrations/readings-webhooks/hook/test").status_code == 502

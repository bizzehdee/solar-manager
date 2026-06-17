"""HTTP + WebSocket API on the dummy (plan.md §7, §21).

These are integration-ish but still hardware-free and deterministic; the full
browser-driven flows live in the Playwright suite (plan.md §21).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.devices.base import Device
from app.devices.dummy import DummyProfile, NullTransport
from app.devices.registry import DeviceRegistry
from app.main import create_app


def _client(midday) -> TestClient:
    clock = lambda: midday  # noqa: E731 — deterministic readings
    reg = DeviceRegistry()
    reg.add(Device("dummy", NullTransport(), DummyProfile(clock=clock), clock=clock))
    app = create_app(settings=Settings(poll_interval_s=60), registry=reg)
    return TestClient(app)


def test_health(midday):
    with _client(midday) as client:
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["control_enabled"] is False  # monitoring-only by default (§12)
        assert body["devices"][0]["device_id"] == "dummy"


def test_live_returns_dummy_metrics(midday):
    with _client(midday) as client:
        body = client.get("/api/live").json()
        metrics = body["devices"]["dummy"]["metrics"]
        assert metrics["pv_power_w"] > 0  # midday -> producing
        assert "battery_soc_pct" in metrics


def test_ws_live_pushes_snapshot(midday):
    with _client(midday) as client:
        with client.websocket_connect("/ws/live") as ws:
            snap = ws.receive_json()
            assert "dummy" in snap["devices"]
            assert "battery_soc_pct" in snap["devices"]["dummy"]["metrics"]

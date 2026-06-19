"""Alert inbox API, notification-channel config, and Prometheus endpoint (plan.md §15/§14).

Alert rule authoring moved to the automation system in L03e-5a–5c; the /api/alert-rules CRUD
and options endpoints have been retired. Alert inbox (list/ack/snooze) stays here."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

_BASE = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def _client() -> TestClient:
    settings = Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600)
    return TestClient(create_app(settings=settings, clock=lambda: _BASE))


def test_alert_channels_config_round_trip_and_options_reflect_it():
    with _client() as client:
        base = client.get("/api/alert-channels").json()
        assert base["channels"] == {} and base["configured"] == []
        assert set(base["supported"]) >= {"webhook", "email", "telegram", "ntfy", "gotify", "pushover"}

        # Configure two channels; one incomplete (dropped from `configured`).
        saved = client.put("/api/alert-channels", json={
            "telegram": {"bot_token": "T", "chat_id": "42"},
            "ntfy": {},  # incomplete
            "bogus": {"x": 1},  # not a supported channel → stripped
        }).json()
        assert saved["configured"] == ["telegram"]
        assert "bogus" not in saved["channels"]


def test_alert_channel_test_endpoint():
    with _client() as client:
        # Not configured → 400.
        assert client.post("/api/alert-channels/webhook/test").status_code == 400

        # Configure webhook, inject a recorder, then a manual test delivers the sample alert.
        client.put("/api/alert-channels", json={"webhook": {"url": "http://hook"}})
        sent: list = []

        async def post(url, payload=None, *, data=None, headers=None):
            sent.append((url, payload))

        client.app.state.automation._channels["webhook"]._post = post
        assert client.post("/api/alert-channels/webhook/test").json() == {"ok": True}
        assert sent and sent[0][0] == "http://hook"


def test_alerts_list_ack_snooze_and_404():
    with _client() as client:
        # No alerts fired yet on a fresh dummy snapshot.
        body = client.get("/api/alerts").json()
        assert body["alerts"] == [] and body["active_count"] == 0
        # Ack/snooze a non-existent alert → 404.
        assert client.post("/api/alerts/999/ack").status_code == 404
        assert client.post("/api/alerts/999/snooze", json={"minutes": 30}).status_code == 404


def test_prometheus_metrics_endpoint():
    with _client() as client:
        text = client.get("/metrics").text
        assert 'solarvolt_battery_soc_pct{device="dummy"}' in text
        # Non-numeric metrics (status strings) are excluded.
        assert "inverter_status" not in text

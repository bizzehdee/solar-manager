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
        assert base["configured"] == []
        assert set(base["supported"]) >= {"email", "telegram", "ntfy", "gotify", "pushover"}

        # Configure a single channel + two custom webhooks (one disabled, one missing url).
        saved = client.put("/api/alert-channels", json={
            "telegram": {"bot_token": "T", "chat_id": "42"},
            "ntfy": {},  # incomplete
            "bogus": {"x": 1},  # not a supported channel → stripped
            "webhooks": [
                {"id": "slack", "label": "Slack", "url": "http://slack", "enabled": True},
                {"label": "Off one", "url": "http://x", "enabled": False},  # id derived from label
            ],
        }).json()
        assert "telegram" in saved["configured"]
        assert "webhook:slack" in saved["configured"]  # enabled + addressed
        assert "webhook:off-one" not in saved["configured"]  # disabled
        assert "bogus" not in saved["channels"]
        assert saved["webhook_labels"]["webhook:slack"] == "Slack"


def test_alert_channel_test_endpoint():
    with _client() as client:
        # Not configured → 400.
        assert client.post("/api/alert-channels/webhook:hook/test").status_code == 400

        # Configure a webhook, inject a recorder, then a manual test delivers the sample alert.
        client.put("/api/alert-channels", json={
            "webhooks": [{"id": "hook", "url": "http://hook", "enabled": True}],
        })
        sent: list = []

        async def post(url, **kw):
            sent.append((url, kw.get("body")))

        client.app.state.automation._channels["webhook:hook"]._post = post
        assert client.post("/api/alert-channels/webhook:hook/test").json() == {"ok": True}
        assert sent and sent[0][0] == "http://hook"


def test_alert_webhook_test_works_when_disabled():
    with _client() as client:
        # A saved-but-disabled webhook can still be tested (verify before enabling).
        client.put("/api/alert-channels", json={
            "webhooks": [{"id": "hook", "url": "http://hook", "enabled": False}],
        })
        captured: list = []

        async def post(url, **kw):
            captured.append(url)

        client.app.state.automation._post = post  # used to build the transient channel
        assert client.post("/api/alert-channels/webhook:hook/test").json() == {"ok": True}
        assert captured == ["http://hook"]


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

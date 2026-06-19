"""Alert + alert-rule API and the Prometheus endpoint, on the dummy (plan.md §15/§14)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

_BASE = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def _client() -> TestClient:
    settings = Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600)
    return TestClient(create_app(settings=settings, clock=lambda: _BASE))


def test_default_rules_seeded_and_listed():
    with _client() as client:
        rules = {r["id"] for r in client.get("/api/alert-rules").json()["rules"]}
        assert {"low_soc", "device_stale", "inverter_fault"} <= rules


def test_alert_rule_crud_and_validation():
    with _client() as client:
        # Create/update via PUT.
        r = client.put("/api/alert-rules/hot", json={
            "name": "Hot inverter", "metric": "inverter_temp_c", "op": "gt", "threshold": 60,
            "hysteresis": 5, "severity": "critical",
        })
        assert r.status_code == 200 and r.json()["op"] == "gt"
        assert any(rule["id"] == "hot" for rule in client.get("/api/alert-rules").json()["rules"])

        # Invalid operator → 422.
        assert client.put("/api/alert-rules/bad", json={"metric": "x", "op": "??"}).status_code == 422

        # Delete.
        assert client.delete("/api/alert-rules/hot").status_code == 204
        assert not any(rule["id"] == "hot" for rule in client.get("/api/alert-rules").json()["rules"])


def test_alert_rule_options_for_editor():
    with _client() as client:
        opts = client.get("/api/alert-rules/options").json()
        # Canonical metrics + the two synthetic engine keys are all offered.
        assert "battery_soc_pct" in opts["metrics"]
        assert "__stale_s__" in opts["metrics"] and "__fault_count__" in opts["metrics"]
        assert opts["ops"] == ["lt", "le", "gt", "ge", "eq", "ne"]
        assert "critical" in opts["severities"]
        # No channels configured by default ⇒ none offered.
        assert opts["channels"] == []


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

        # The rule editor now offers the configured channel.
        assert client.get("/api/alert-rules/options").json()["channels"] == ["telegram"]


def test_alert_channel_test_endpoint():
    with _client() as client:
        # Not configured → 400.
        assert client.post("/api/alert-channels/webhook/test").status_code == 400

        # Configure webhook, inject a recorder, then a manual test delivers the sample alert.
        client.put("/api/alert-channels", json={"webhook": {"url": "http://hook"}})
        sent: list = []

        async def post(url, payload=None, *, data=None, headers=None):
            sent.append((url, payload))

        client.app.state.alerts._channels["webhook"]._post = post
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

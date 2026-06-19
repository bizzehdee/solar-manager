"""Suggest-only automation API (L03e-2): rule CRUD, gating, preview/options wiring on the dummy.

The dummy's settings schema marks the work-mode timer scheduling fields automation-safe, so the
allow-list + preview can be exercised with no hardware. Automation never writes here."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.automation.rules import allow_list_from_schema
from app.config import Settings
from app.main import create_app

# 2026-06-20 is a Saturday.
_SAT = datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)


def _client(*, automation=True) -> TestClient:
    settings = Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600,
                        enable_automation=automation)
    return TestClient(create_app(settings=settings, clock=lambda: _SAT))


def _weekend_rule(soc=80, enabled=True, action_enabled=True, priority=0) -> dict:
    return {
        "name": "Weekend top-up", "match": "all", "priority": priority, "enabled": enabled,
        "conditions": [{"kind": "day_of_week", "params": {"days": [5, 6]}}],
        "actions": [{"target": {"section": "timer_slots", "field": "target_soc_pct", "index": 1},
                     "value": soc, "enabled": action_enabled}],
    }


def test_automation_gated_off_returns_403():
    with _client(automation=False) as client:
        assert client.get("/api/automation/rules").status_code == 403
        assert client.get("/api/automation/preview").status_code == 403
        assert client.put("/api/automation/rules/x", json=_weekend_rule()).status_code == 403


def test_rule_crud_and_validation():
    with _client() as client:
        assert client.get("/api/automation/rules").json()["rules"] == []

        r = client.put("/api/automation/rules/weekend", json=_weekend_rule())
        assert r.status_code == 200 and r.json()["id"] == "weekend"
        assert [x["id"] for x in client.get("/api/automation/rules").json()["rules"]] == ["weekend"]

        # Invalid condition kind → 422.
        bad = {"conditions": [{"kind": "phase_of_moon"}], "actions": []}
        assert client.put("/api/automation/rules/bad", json=bad).status_code == 422

        # Delete (and 404 on a second delete).
        assert client.delete("/api/automation/rules/weekend").status_code == 204
        assert client.delete("/api/automation/rules/weekend").status_code == 404


def test_options_lists_targets_with_safety_status():
    with _client() as client:
        opts = client.get("/api/automation/options").json()
        assert "day_of_week" in opts["condition_kinds"] and "tariff_window" in opts["condition_kinds"]
        assert "battery_soc_pct" in opts["metrics"]
        timer_soc = next(t for t in opts["targets"]
                         if t["section"] == "timer_slots" and t["field"] == "target_soc_pct")
        assert timer_soc["status"] == "ok" and timer_soc["repeating"] is True and timer_soc["count"] == 6
        # A writable-but-not-automation-safe field is offered but flagged at_risk.
        risky = next(t for t in opts["targets"] if t["status"] == "at_risk")
        assert risky["section"] != "timer_slots" or risky["field"] not in {"target_soc_pct", "start_time"}


def test_preview_shows_armed_change_on_saturday():
    with _client() as client:
        client.put("/api/automation/rules/weekend", json=_weekend_rule(soc=80))
        body = client.get("/api/automation/preview").json()
        changes = body["decision"]["changes"]
        assert len(changes) == 1
        change = changes[0]
        assert change["value"] == 80 and change["status"] == "ok"
        assert change["active"] is True and change["will_apply"] is True
        assert change["target"] == {"section": "timer_slots", "field": "target_soc_pct", "index": 1}


def test_preview_disabled_rule_is_preview_only():
    with _client() as client:
        client.put("/api/automation/rules/weekend", json=_weekend_rule(enabled=False))
        change = client.get("/api/automation/preview").json()["decision"]["changes"][0]
        assert change["active"] is False and change["will_apply"] is False  # shown, not applied


def test_preview_metric_condition_uses_live_snapshot():
    with _client() as client:
        # The dummy reports a numeric battery SoC; a high threshold makes "SoC < 200" always match.
        rule = {
            "name": "Low SoC top-up", "enabled": True,
            "conditions": [{"kind": "metric", "params": {"metric": "battery_soc_pct", "op": "lt", "threshold": 200}}],
            "actions": [{"target": {"section": "timer_slots", "field": "target_soc_pct", "index": 0},
                         "value": 50, "enabled": True}],
        }
        client.put("/api/automation/rules/lowsoc", json=rule)
        changes = client.get("/api/automation/preview").json()["decision"]["changes"]
        assert changes and changes[0]["value"] == 50


def test_allow_list_from_schema_empty_when_no_schema():
    allow = allow_list_from_schema(None)
    assert allow.safe == frozenset() and allow.writable == frozenset()
    assert allow.status("timer_slots", "target_soc_pct") == "blocked"

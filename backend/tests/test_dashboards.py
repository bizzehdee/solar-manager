"""Dashboard model + API (plan.md §8; task L06 / T_DB1).

Builtins (Now, History) are seeded from code; user dashboards round-trip through app_config.
Covers CRUD, builtin protection, unknown-id 404, validation, and export/import (the single-
dashboard JSON is the wire format).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import pytest

from app.config import Settings
from app.dashboards import _validate
from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app(settings=Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600)))


def test_list_includes_seeded_builtins_first():
    with _client() as client:
        body = client.get("/api/dashboards").json()
        ids = [d["id"] for d in body["dashboards"]]
        assert ids[:2] == ["now", "history"]  # builtins first, in declaration order
        assert all(d["builtin"] for d in body["dashboards"][:2])


def test_get_builtin_now_has_expected_layout():
    with _client() as client:
        now = client.get("/api/dashboards/now").json()
        assert now["builtin"] is True
        ef = next(w for w in now["widgets"] if w["type"] == "energy-flow")
        assert (ef["x"], ef["y"], ef["w"], ef["h"]) == (0, 0, 6, 6)
        soc = next(w for w in now["widgets"] if w["type"] == "soc-gauge")
        assert soc["config"]["metric"] == "battery_soc_pct"


def test_get_unknown_is_404():
    with _client() as client:
        assert client.get("/api/dashboards/nope").status_code == 404


def test_user_dashboard_crud_roundtrip():
    with _client() as client:
        payload = {
            "name": "Garage",
            "widgets": [{"type": "soc-gauge", "x": 0, "y": 0, "w": 2, "h": 2, "config": {"metric": "battery_soc_pct"}}],
        }
        r = client.put("/api/dashboards/garage", json=payload)
        assert r.status_code == 200
        saved = r.json()
        assert saved == {
            "id": "garage",
            "name": "Garage",
            "builtin": False,
            "widgets": [{"type": "soc-gauge", "x": 0, "y": 0, "w": 2, "h": 2, "config": {"metric": "battery_soc_pct"}}],
        }

        # Appears in the list (after builtins) and is fetchable by id.
        ids = [d["id"] for d in client.get("/api/dashboards").json()["dashboards"]]
        assert "garage" in ids
        assert client.get("/api/dashboards/garage").json() == saved

        # Update replaces it.
        saved["name"] = "Garage 2"
        r = client.put("/api/dashboards/garage", json=saved)
        assert r.json()["name"] == "Garage 2"

        # Delete removes it.
        assert client.delete("/api/dashboards/garage").status_code == 204
        assert client.get("/api/dashboards/garage").status_code == 404


def test_export_then_import_under_new_id():
    """GET is the export wire format; PUT with a chosen id is import."""
    with _client() as client:
        exported = client.get("/api/dashboards/now").json()  # builtin as a template
        r = client.put("/api/dashboards/my-now", json=exported)
        assert r.status_code == 200
        imported = r.json()
        assert imported["id"] == "my-now"
        assert imported["builtin"] is False  # imported copies are user dashboards
        assert len(imported["widgets"]) == len(exported["widgets"])


def test_builtin_writes_are_forbidden():
    with _client() as client:
        assert client.put("/api/dashboards/now", json={"name": "x", "widgets": []}).status_code == 403
        assert client.delete("/api/dashboards/history").status_code == 403


def test_delete_unknown_is_404():
    with _client() as client:
        assert client.delete("/api/dashboards/ghost").status_code == 404


def test_put_rejects_invalid_body():
    with _client() as client:
        assert client.put("/api/dashboards/bad", json={"widgets": []}).status_code == 422  # no name
        assert client.put("/api/dashboards/bad", json={"name": "X", "widgets": "no"}).status_code == 422
        assert client.put("/api/dashboards/bad", json={"name": "X", "widgets": [{"x": 0}]}).status_code == 422  # no type
        # widget config must be an object, not a scalar
        assert client.put(
            "/api/dashboards/bad", json={"name": "X", "widgets": [{"type": "t", "config": "no"}]}
        ).status_code == 422


def test_validate_rejects_non_object_body():
    with pytest.raises(ValueError):
        _validate("x", ["not", "a", "dict"])

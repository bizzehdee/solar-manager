"""Control write API — flag gating, status codes, concurrency, audit (tasks T076/T078).

Drives the real FastAPI app on the dummy. SOLARVOLT_ENABLE_CONTROL gates the whole write
surface: off ⇒ 403 + control capability suppressed; on ⇒ the validate→write→read-back flow
runs in-memory (zero risk) and every write is audited.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

_BASE = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def _client(*, control: bool) -> TestClient:
    settings = Settings(
        enable_control=control, poll_interval_s=60, db_path=":memory:", persist_interval_s=3600
    )
    return TestClient(create_app(settings=settings, clock=lambda: _BASE))


# --- gating (§12) ---------------------------------------------------------------
def test_write_forbidden_when_control_disabled():
    with _client(control=False) as client:
        # Reading settings still works (monitoring); the control flag is suppressed.
        got = client.get("/api/devices/dummy/settings").json()
        assert got["supported"] is True
        assert got["control_enabled"] is False
        r = client.put("/api/devices/dummy/settings", json={"section": "globals", "values": {"grid_charge": False}})
        assert r.status_code == 403

        dev = next(d for d in client.get("/api/devices").json()["devices"] if d["id"] == "dummy")
        assert dev["control"] is False and dev["settings"] is True


def test_device_advertises_control_when_enabled():
    with _client(control=True) as client:
        dev = next(d for d in client.get("/api/devices").json()["devices"] if d["id"] == "dummy")
        assert dev["control"] is True
        assert client.get("/api/devices/dummy/settings").json()["control_enabled"] is True


# --- happy path + audit ---------------------------------------------------------
def test_write_applies_verifies_and_audits():
    with _client(control=True) as client:
        before = client.get("/api/devices/dummy/settings").json()
        assert before["values"]["globals"]["max_sell_power_w"] == 8000.0

        r = client.put(
            "/api/devices/dummy/settings",
            json={"section": "globals", "values": {"max_sell_power_w": 5000}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["mismatches"] == []
        assert body["changes"] == {"max_sell_power_w": {"old": 8000.0, "new": 5000}}
        assert r.headers["ETag"] == body["etag"]
        # Read-back through the API reflects the write.
        assert client.get("/api/devices/dummy/settings").json()["values"]["globals"]["max_sell_power_w"] == 5000

        audit = client.get("/api/audit").json()["entries"]
        assert len(audit) == 1
        assert audit[0]["section"] == "globals" and audit[0]["result"] == "ok"
        assert audit[0]["changes"]["max_sell_power_w"]["new"] == 5000


def test_write_timer_slot_with_index_and_audit_slot():
    with _client(control=True) as client:
        r = client.put(
            "/api/devices/dummy/settings",
            json={"section": "timer_slots", "index": 3, "values": {"target_soc_pct": 75}},
        )
        assert r.status_code == 200 and r.json()["ok"] is True
        assert client.get("/api/devices/dummy/settings").json()["values"]["timer_slots"][3]["target_soc_pct"] == 75
        assert client.get("/api/audit").json()["entries"][0]["slot"] == 3


# --- error mapping --------------------------------------------------------------
def test_validation_error_is_422():
    with _client(control=True) as client:
        r = client.put(
            "/api/devices/dummy/settings",
            json={"section": "globals", "values": {"work_mode": 999}},
        )
        assert r.status_code == 422
        assert "errors" in r.json()["detail"]


def test_unknown_field_is_422():
    with _client(control=True) as client:
        r = client.put(
            "/api/devices/dummy/settings",
            json={"section": "globals", "values": {"nope": 1}},
        )
        assert r.status_code == 422


def test_stale_if_match_is_412():
    with _client(control=True) as client:
        r = client.put(
            "/api/devices/dummy/settings",
            headers={"If-Match": "deadbeef"},
            json={"section": "globals", "values": {"grid_charge": False}},
        )
        assert r.status_code == 412
        assert "current_etag" in r.json()["detail"]


def test_matching_etag_allows_write():
    with _client(control=True) as client:
        etag = client.get("/api/devices/dummy/settings").json()["etag"]
        r = client.put(
            "/api/devices/dummy/settings",
            headers={"If-Match": etag},
            json={"section": "globals", "values": {"grid_charge": False}},
        )
        assert r.status_code == 200 and r.json()["ok"] is True


def test_missing_section_is_422():
    with _client(control=True) as client:
        r = client.put("/api/devices/dummy/settings", json={"values": {"grid_charge": False}})
        assert r.status_code == 422


def test_audit_empty_initially():
    with _client(control=True) as client:
        assert client.get("/api/audit").json()["entries"] == []

"""Formatting preferences API (plan.md §19 / T093)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app(settings=Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600)))


def test_preferences_default_and_roundtrip():
    with _client() as client:
        assert client.get("/api/preferences").json() == {"locale": "en-US"}  # default

        r = client.put("/api/preferences", json={"locale": "en-GB", "currency": "GBP", "bogus": "x"})
        assert r.status_code == 200
        saved = r.json()
        assert saved == {"locale": "en-GB", "currency": "GBP"}  # unknown keys dropped
        assert client.get("/api/preferences").json() == saved

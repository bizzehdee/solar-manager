"""SPA deep-link fallback for the backend-served frontend build.

When the built UI is present, the backend mounts it at `/`. Angular's client-side
routes (e.g. /now, /forecast) have no file on disk, so a hard refresh or bookmark must
fall back to index.html rather than 404. Real missing assets still 404. Skips when no
build is present (a bare unit run with no prior `ng build`)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import _FRONTEND_DIST, create_app

pytestmark = pytest.mark.skipif(
    not _FRONTEND_DIST.is_dir(), reason="frontend build not present (run `make build`)"
)


def _client() -> TestClient:
    return TestClient(create_app(settings=Settings(poll_interval_s=60, db_path=":memory:")))


def test_root_serves_index():
    with _client() as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "<html" in r.text.lower()


def test_client_side_route_falls_back_to_index():
    # A client-side route with no file on disk should serve the SPA shell, not 404.
    with _client() as client:
        r = client.get("/now")
        assert r.status_code == 200
        assert "<html" in r.text.lower()


def test_api_route_not_shadowed_by_spa_fallback():
    # /api is registered before the static mount — it must NOT fall back to index.html.
    with _client() as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"]


def test_missing_asset_still_404s():
    # A path that looks like a real asset (has an extension) shouldn't be masked as the shell.
    with _client() as client:
        assert client.get("/does-not-exist.js").status_code == 404

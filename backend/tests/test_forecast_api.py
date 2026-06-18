"""Forecast API on the dummy with an injected (network-free) weather client (T063/T064)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.forecast.openmeteo import OpenMeteoClient
from app.main import create_app

_BASE = datetime(2026, 6, 21, 3, 0, tzinfo=timezone.utc)


def _fake_weather() -> OpenMeteoClient:
    """A weather client backed by canned hourly data — no network."""
    times = [(_BASE + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(12)]
    # A daytime irradiance bump around the middle of the window.
    ghi = [max(0.0, 700.0 - abs(h - 6) * 120.0) for h in range(12)]

    async def fetch(url):
        return {
            "hourly": {
                "time": times,
                "shortwave_radiation": ghi,
                "cloud_cover": [20] * 12,
                "temperature_2m": [18.0] * 12,
            }
        }

    return OpenMeteoClient(fetch=fetch, clock=lambda: _BASE)


def _client() -> TestClient:
    settings = Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600)
    return TestClient(create_app(settings=settings, clock=lambda: _BASE, weather=_fake_weather()))


def test_forecast_returns_generation_and_soc():
    with _client() as client:
        body = client.get("/api/forecast").json()
        assert body["device_id"] == "dummy"
        assert len(body["generation"]) == 12
        assert len(body["soc"]) == 12
        # Daytime hours should project some PV generation.
        assert any(g["pv_w"] > 0 for g in body["generation"])
        # SoC stays within the configured window.
        assert all(0 <= p["soc_pct"] <= 100 for p in body["soc"])
        assert "expected_today_wh" in body


def test_forecast_config_get_and_put():
    with _client() as client:
        cfg = client.get("/api/forecast/config").json()
        assert "site" in cfg and "arrays" in cfg and "battery" in cfg

        r = client.put("/api/forecast/config", json={
            "site": {"lat": 40.0, "lon": -3.0, "performance_ratio": 0.8},
            "arrays": [{"name": "Roof", "kwp": 5.0, "tilt": 30, "azimuth": 180}],
            "battery": {"capacity_wh": 12000.0, "min_soc_pct": 15.0},
        })
        assert r.status_code == 200
        back = r.json()
        assert back["site"]["lat"] == 40.0
        assert back["arrays"][0]["kwp"] == 5.0
        assert back["battery"]["capacity_wh"] == 12000.0

"""Open-Meteo client: parse, cache/TTL, failure fallback (task T060)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.forecast.openmeteo import OpenMeteoClient

_T0 = datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc)


def _sample() -> dict:
    return {
        "hourly": {
            "time": ["2026-06-21T00:00", "2026-06-21T01:00"],
            "shortwave_radiation": [0.0, 250.0],
            "cloud_cover": [10, 20],
            "temperature_2m": [12.0, 13.5],
        }
    }


async def test_parse_weather_points():
    async def fetch(url):
        return _sample()

    pts = await OpenMeteoClient(fetch=fetch, clock=lambda: _T0).forecast(51.5, -0.13)
    assert len(pts) == 2
    assert pts[1].ghi == 250.0 and pts[1].cloud_cover == 20.0 and pts[1].temp_c == 13.5
    assert pts[0].ts == _T0.timestamp()


async def test_caches_within_ttl_then_refetches():
    calls = []
    now = [_T0]

    async def fetch(url):
        calls.append(url)
        return _sample()

    c = OpenMeteoClient(fetch=fetch, ttl_s=3600, clock=lambda: now[0])
    await c.forecast(51.5, -0.13)
    now[0] = _T0 + timedelta(seconds=1800)   # within TTL
    await c.forecast(51.5, -0.13)
    assert len(calls) == 1                    # served from cache
    now[0] = _T0 + timedelta(seconds=4000)   # past TTL
    await c.forecast(51.5, -0.13)
    assert len(calls) == 2                    # refetched


async def test_days_param_in_url_and_cached_per_range():
    urls = []

    async def fetch(url):
        urls.append(url)
        return _sample()

    c = OpenMeteoClient(fetch=fetch, clock=lambda: _T0)
    await c.forecast(51.5, -0.13, days=7)
    await c.forecast(51.5, -0.13, days=7)   # cached -> no new fetch
    await c.forecast(51.5, -0.13, days=3)   # different range -> separate cache entry
    assert "forecast_days=7" in urls[0]
    assert len(urls) == 2 and "forecast_days=3" in urls[1]


async def test_days_clamped_to_max():
    urls = []

    async def fetch(url):
        urls.append(url)
        return _sample()

    await OpenMeteoClient(fetch=fetch, clock=lambda: _T0).forecast(51.5, -0.13, days=99)
    assert f"forecast_days={OpenMeteoClient.MAX_DAYS}" in urls[0]


async def test_failure_returns_cached_then_empty():
    state = {"ok": True}
    now = [_T0]

    async def fetch(url):
        if not state["ok"]:
            raise RuntimeError("network down")
        return _sample()

    c = OpenMeteoClient(fetch=fetch, ttl_s=1.0, clock=lambda: now[0])
    assert len(await c.forecast(51.5, -0.13)) == 2   # success, cached
    state["ok"] = False
    now[0] = _T0 + timedelta(seconds=10)             # TTL expired -> refetch fails
    assert len(await c.forecast(51.5, -0.13)) == 2   # falls back to cached

    # A different location with no cache and a failing fetch -> empty list, no raise.
    assert await c.forecast(0.0, 0.0) == []

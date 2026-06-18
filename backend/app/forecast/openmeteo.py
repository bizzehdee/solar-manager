"""Open-Meteo weather client + cache (plan.md §6; task T060).

Fetches the hourly forecast Solar Manager needs — global horizontal irradiance
(`shortwave_radiation`), `cloud_cover`, `temperature_2m` — for a lat/lon, and caches it
(default 6 h TTL ⇒ a few refreshes a day; Open-Meteo is free, no key needed).

Egress is off the hot path (plan.md): a failed fetch returns the last good cached data, or
an empty list, and logs a warning — it never blocks polling/persistence. The HTTP call is
injectable (`fetch`) so tests run with no network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

log = logging.getLogger("solar_manager.forecast")

_BASE_URL = "https://api.open-meteo.com/v1/forecast"
_HOURLY = "shortwave_radiation,cloud_cover,temperature_2m"

# fetch(url) -> parsed JSON dict.
Fetch = Callable[[str], Awaitable[dict]]


@dataclass(frozen=True, slots=True)
class WeatherPoint:
    ts: float            # epoch seconds (UTC)
    ghi: float           # W/m² global horizontal irradiance
    cloud_cover: float   # %
    temp_c: float        # °C


async def _httpx_fetch(url: str) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OpenMeteoClient:
    def __init__(
        self,
        *,
        fetch: Fetch | None = None,
        ttl_s: float = 21600.0,
        forecast_days: int = 2,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._fetch = fetch or _httpx_fetch
        self._ttl = ttl_s
        self._forecast_days = forecast_days
        self._clock = clock
        self._cache: dict[tuple[float, float], tuple[float, list[WeatherPoint]]] = {}

    def _url(self, lat: float, lon: float) -> str:
        return (
            f"{_BASE_URL}?latitude={lat}&longitude={lon}&hourly={_HOURLY}"
            f"&forecast_days={self._forecast_days}&timezone=UTC"
        )

    async def forecast(self, lat: float, lon: float) -> list[WeatherPoint]:
        """Hourly weather for (lat, lon), served from cache within the TTL. On a failed
        refresh, returns the last cached value if any, else an empty list."""
        key = (round(lat, 3), round(lon, 3))
        now = self._clock().timestamp()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]
        try:
            data = await self._fetch(self._url(lat, lon))
            points = self._parse(data)
        except Exception as exc:  # network/parse failure — degrade, never raise
            log.warning("Open-Meteo fetch failed for %s: %s", key, exc)
            return cached[1] if cached else []
        self._cache[key] = (now, points)
        return points

    @staticmethod
    def _parse(data: dict) -> list[WeatherPoint]:
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        ghi = hourly.get("shortwave_radiation", [])
        cloud = hourly.get("cloud_cover", [])
        temp = hourly.get("temperature_2m", [])
        out: list[WeatherPoint] = []
        for i, t in enumerate(times):
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out.append(
                WeatherPoint(
                    ts=dt.timestamp(),
                    ghi=float(ghi[i]) if i < len(ghi) and ghi[i] is not None else 0.0,
                    cloud_cover=float(cloud[i]) if i < len(cloud) and cloud[i] is not None else 0.0,
                    temp_c=float(temp[i]) if i < len(temp) and temp[i] is not None else 15.0,
                )
            )
        return out

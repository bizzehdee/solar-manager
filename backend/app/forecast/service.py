"""Forecast orchestration (plan.md §6; task T063).

Pulls the site/array/battery config + a historical load profile + the weather forecast,
runs the PV model and the SoC projection, and assembles the `/api/forecast` payload:
an expected-generation curve, a projected-SoC line, projected depletion/full times, and a
lightweight forecast-vs-actual accuracy for today.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..storage.repository import AppConfigRepository, SqliteHistoryRepository
from . import model
from .battery import BatterySpec, first_time_at_or_above, first_time_at_or_below, project_soc
from .openmeteo import OpenMeteoClient

# Sensible default site/battery so a fresh install still renders a forecast on the dummy.
_DEFAULT_SITE = {"lat": 51.5, "lon": -0.13, "performance_ratio": model.DEFAULT_PR}
_DEFAULT_ARRAYS = [{"name": "Array 1", "kwp": 3.5, "tilt": 35, "azimuth": 135},
                   {"name": "Array 2", "kwp": 3.0, "tilt": 35, "azimuth": 225}]
_DEFAULT_BATTERY = {"capacity_wh": 16000.0, "min_soc_pct": 10.0, "max_soc_pct": 100.0}


class ForecastService:
    def __init__(
        self,
        history_repo: SqliteHistoryRepository,
        config_repo: AppConfigRepository,
        weather: OpenMeteoClient,
    ) -> None:
        self._repo = history_repo
        self._config = config_repo
        self._weather = weather

    async def config(self) -> dict:
        site = {**_DEFAULT_SITE, **(await self._config.get("site", {}) or {})}
        arrays = await self._config.get("arrays", None) or _DEFAULT_ARRAYS
        battery = {**_DEFAULT_BATTERY, **(await self._config.get("battery", {}) or {})}
        return {"site": site, "arrays": arrays, "battery": battery}

    async def _load_profile(self, device_id: str) -> dict[int, float]:
        """Average load (W) by hour-of-day over recent history (hourly rollups). Falls
        back to a flat default when there's no history yet."""
        now = datetime.now(timezone.utc).timestamp()
        start = now - 14 * 86400
        pts = await self._repo.query(device_id, "load_power_w", start, now, "1h")
        buckets: dict[int, list[float]] = {}
        for p in pts:
            hour = datetime.fromtimestamp(p.ts, tz=timezone.utc).hour
            buckets.setdefault(hour, []).append(p.value)
        return {h: sum(v) / len(v) for h, v in buckets.items()}

    async def forecast(self, device_id: str) -> dict:
        cfg = await self.config()
        site, arrays_cfg, battery_cfg = cfg["site"], cfg["arrays"], cfg["battery"]
        lat, lon = site["lat"], site["lon"]
        pr = site.get("performance_ratio", model.DEFAULT_PR)
        segments = [model.ArraySegment.from_dict(a) for a in arrays_cfg]
        battery = BatterySpec.from_dict(battery_cfg)

        weather = await self._weather.forecast(lat, lon)
        profile = await self._load_profile(device_id)
        default_load = (sum(profile.values()) / len(profile)) if profile else 400.0

        generation: list[dict] = []
        hourly: list[tuple[float, float, float]] = []
        for wp in weather:
            dt = datetime.fromtimestamp(wp.ts, tz=timezone.utc)
            pv_w = model.expected_power_w(segments, lat, lon, dt, wp.ghi, wp.temp_c, pr)
            load_w = profile.get(dt.hour, default_load)
            generation.append({"ts": wp.ts, "pv_w": round(pv_w, 1), "ghi": wp.ghi, "temp_c": wp.temp_c})
            hourly.append((wp.ts, pv_w, load_w))

        start_soc = await self._repo.latest(device_id, "battery_soc_pct")
        soc_points = project_soc(start_soc if start_soc is not None else 50.0, hourly, battery)

        return {
            "device_id": device_id,
            "generation": generation,
            "soc": [p.as_dict() for p in soc_points],
            "depletion_ts": first_time_at_or_below(soc_points, battery.min_soc_pct),
            "full_ts": first_time_at_or_above(soc_points, battery.max_soc_pct),
            "expected_today_wh": round(self._today_energy(generation), 1),
            "currency": None,
        }

    @staticmethod
    def _today_energy(generation: list[dict]) -> float:
        """Trapezoidal Wh of the expected-generation curve for the current UTC day."""
        from .. import energy

        today = datetime.now(timezone.utc).date()
        pts = [
            (g["ts"], g["pv_w"]) for g in generation
            if datetime.fromtimestamp(g["ts"], tz=timezone.utc).date() == today
        ]
        return energy.integrate_wh(pts, max_gap_s=7200.0)

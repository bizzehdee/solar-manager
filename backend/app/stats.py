"""Statistics engine (plan.md §3, §7; tasks T050/T052/T055).

Turns persisted history into daily/period statistics: energy totals per stream,
self-consumption / self-sufficiency, peak PV, battery round-trip efficiency, and — via
the tariff + economic factors — cost / savings / CO₂. The arithmetic lives in the pure
modules (`energy`, `tariff`, `economics`); this service just pulls the right series from
the repository and assembles them.

Energy totals prefer the inverter's own **daily counters** (`today_*_wh`): the daily
rollup's `last` value is that day's running total at day end. When a counter is absent we
fall back to **integrating power** over the day (plan.md §10 / §5).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from . import economics, energy
from .storage.repository import AppConfigRepository, SqliteHistoryRepository
from .tariff import Tariff, hourly_deltas

DAY_S = 86400.0

# canonical stream -> (daily counter metric, instantaneous power metric for fallback)
_STREAMS: dict[str, tuple[str, str | None]] = {
    "pv": ("today_pv_wh", "pv_power_w"),
    "load": ("today_load_wh", "load_power_w"),
    "import": ("today_grid_import_wh", None),
    "export": ("today_grid_export_wh", None),
    "charge": ("today_batt_charge_wh", None),
    "discharge": ("today_batt_discharge_wh", None),
}

_DEFAULT_ECON = {"co2_intensity_g_per_kwh": 233.0, "system_cost": 0.0, "lifetime_years": 25.0}


@dataclass(frozen=True, slots=True)
class DailyStats:
    device_id: str
    date: str                      # ISO date (UTC) of the day's start
    energy_wh: dict[str, float]
    self_consumption_pct: float | None
    self_sufficiency_pct: float | None
    peak_pv_w: float | None
    round_trip_efficiency: float | None
    economics: dict
    currency: str

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


class StatsService:
    def __init__(self, history_repo: SqliteHistoryRepository, config_repo: AppConfigRepository) -> None:
        self._repo = history_repo
        self._config = config_repo

    async def tariff(self) -> Tariff:
        return Tariff.from_dict(await self._config.get("tariff", {}) or {})

    async def _econ_factors(self) -> dict:
        return {**_DEFAULT_ECON, **(await self._config.get("economics", {}) or {})}

    async def _daily_total(self, device_id: str, start: float, end: float, stream: str) -> float:
        counter, power = _STREAMS[stream]
        pts = await self._repo.query(device_id, counter, start, end, "1d")
        if pts and pts[-1].last is not None:
            return float(pts[-1].last)
        # Fallback: integrate the power series if there's a power metric for this stream.
        if power is not None:
            raw = await self._repo.query(device_id, power, start, end, "5m")
            return energy.integrate_wh([(p.ts, p.value) for p in raw])
        return 0.0

    async def _priced(self, device_id: str, start: float, end: float, counter: str, schedule) -> float:
        """Cost/revenue of a counter stream over the day, attributing hourly energy
        deltas to TOU windows (so time-of-use rates are respected)."""
        pts = await self._repo.query(device_id, counter, start, end, "1h")
        deltas = hourly_deltas([(p.ts, p.last if p.last is not None else p.value) for p in pts])
        return schedule.cost_of_deltas(deltas)

    async def daily(self, device_id: str, day_start: float) -> DailyStats:
        start = float(int(day_start // DAY_S) * DAY_S)
        end = start + DAY_S
        e = {s: await self._daily_total(device_id, start, end, s) for s in _STREAMS}

        peak_pts = await self._repo.query(device_id, "pv_power_w", start, end, "1d")
        peak_pv = peak_pts[-1].max if peak_pts else None

        tariff = await self.tariff()
        import_sched, export_sched = tariff.schedules_for(datetime.fromtimestamp(start, tz=timezone.utc))
        import_cost = await self._priced(device_id, start, end, "today_grid_import_wh", import_sched)
        export_rev = await self._priced(device_id, start, end, "today_grid_export_wh", export_sched)
        baseline = await self._priced(device_id, start, end, "today_load_wh", import_sched)

        factors = await self._econ_factors()
        econ = economics.compute_economics(
            import_cost=import_cost,
            export_revenue=export_rev,
            baseline_cost=baseline,
            pv_wh=e["pv"],
            export_wh=e["export"],
            co2_intensity_g_per_kwh=factors["co2_intensity_g_per_kwh"],
            standing_charge=tariff.standing_charge,
        )

        sc = energy.self_consumption_ratio(e["pv"], e["export"])
        ss = energy.self_sufficiency_ratio(e["load"], e["import"])
        rte = economics.round_trip_efficiency(e["charge"], e["discharge"])

        return DailyStats(
            device_id=device_id,
            date=datetime.fromtimestamp(start, tz=timezone.utc).date().isoformat(),
            energy_wh={k: round(v, 1) for k, v in e.items()},
            self_consumption_pct=None if sc is None else round(sc * 100, 1),
            self_sufficiency_pct=None if ss is None else round(ss * 100, 1),
            peak_pv_w=peak_pv,
            round_trip_efficiency=None if rte is None else round(rte, 3),
            economics=econ.as_dict(),
            currency=tariff.currency,
        )

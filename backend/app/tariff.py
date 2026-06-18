"""Tariff model (plan.md §5, Decision #5; task T051) — §21 critical logic.

Import (purchase) and export (feed-in) prices, each either a **flat** rate or a set of
**time-of-use** windows, with optional **seasonal** variants. Pure data + lookup:
`rate_at(hour)` for a schedule, `cost_of_deltas(hourly_wh, schedule)` to price a day's
energy. Serialises to/from plain dicts so it can live in the config DB.

Rates are currency-per-kWh; energy is passed in Wh and converted internally.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class TouWindow:
    """A time-of-use window [start_hour, end_hour) at `rate` (per kWh). Supports wrap
    (e.g. a night rate 23:00→07:00 with start=23, end=7)."""

    start_hour: float
    end_hour: float
    rate: float

    def contains(self, hour: float) -> bool:
        if self.start_hour <= self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour  # wraps midnight


@dataclass(frozen=True, slots=True)
class RateSchedule:
    """A flat rate and/or TOU windows. Windows win where they apply; `flat` is the
    fallback (and the whole schedule when there are no windows)."""

    flat: float = 0.0
    windows: tuple[TouWindow, ...] = ()

    def rate_at(self, hour: float) -> float:
        for w in self.windows:
            if w.contains(hour):
                return w.rate
        return self.flat

    def cost_of_deltas(self, hourly_wh: Iterable[tuple[float, float]]) -> float:
        """Price a sequence of (hour_of_day, wh) energy deltas at this schedule."""
        return sum((wh / 1000.0) * self.rate_at(hour) for hour, wh in hourly_wh)

    @classmethod
    def from_dict(cls, d: dict | float | None) -> "RateSchedule":
        if d is None:
            return cls()
        if isinstance(d, (int, float)):
            return cls(flat=float(d))
        windows = tuple(
            TouWindow(float(w["start_hour"]), float(w["end_hour"]), float(w["rate"]))
            for w in d.get("windows", [])
        )
        return cls(flat=float(d.get("flat", 0.0)), windows=windows)

    def to_dict(self) -> dict:
        return {
            "flat": self.flat,
            "windows": [
                {"start_hour": w.start_hour, "end_hour": w.end_hour, "rate": w.rate}
                for w in self.windows
            ],
        }


@dataclass(frozen=True, slots=True)
class Season:
    """A seasonal override active for calendar months in [start_month, end_month]
    (inclusive, 1–12, wrap-aware so e.g. winter Nov→Feb is start=11,end=2)."""

    start_month: int
    end_month: int
    import_rate: RateSchedule
    export_rate: RateSchedule

    def contains_month(self, month: int) -> bool:
        if self.start_month <= self.end_month:
            return self.start_month <= month <= self.end_month
        return month >= self.start_month or month <= self.end_month


@dataclass(frozen=True, slots=True)
class Tariff:
    """Default import/export schedules + optional seasonal overrides, plus a fixed daily
    **standing charge** (currency/day) that applies regardless of usage."""

    import_rate: RateSchedule = field(default_factory=RateSchedule)
    export_rate: RateSchedule = field(default_factory=RateSchedule)
    currency: str = "GBP"
    standing_charge: float = 0.0   # fixed cost per day (currency), independent of energy
    seasons: tuple[Season, ...] = ()

    def schedules_for(self, when: datetime) -> tuple[RateSchedule, RateSchedule]:
        """Return (import, export) schedules effective on `when`, applying the first
        matching season override if any."""
        for s in self.seasons:
            if s.contains_month(when.month):
                return s.import_rate, s.export_rate
        return self.import_rate, self.export_rate

    @classmethod
    def from_dict(cls, d: dict) -> "Tariff":
        seasons = tuple(
            Season(
                int(s["start_month"]), int(s["end_month"]),
                RateSchedule.from_dict(s.get("import_rate")),
                RateSchedule.from_dict(s.get("export_rate")),
            )
            for s in d.get("seasons", [])
        )
        return cls(
            import_rate=RateSchedule.from_dict(d.get("import_rate")),
            export_rate=RateSchedule.from_dict(d.get("export_rate")),
            currency=d.get("currency", "GBP"),
            standing_charge=float(d.get("standing_charge", 0.0)),
            seasons=seasons,
        )

    def to_dict(self) -> dict:
        return {
            "currency": self.currency,
            "standing_charge": self.standing_charge,
            "import_rate": self.import_rate.to_dict(),
            "export_rate": self.export_rate.to_dict(),
            "seasons": [
                {
                    "start_month": s.start_month, "end_month": s.end_month,
                    "import_rate": s.import_rate.to_dict(),
                    "export_rate": s.export_rate.to_dict(),
                }
                for s in self.seasons
            ],
        }


def hourly_deltas(series: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Turn a series of cumulative-counter readings (epoch_ts, counter_wh) into
    per-step (hour_of_day, delta_wh) energy increments, reset-aware (a drop below half
    the previous value is a midnight/cycle reset, counted from zero). Used to attribute a
    day's grid import/export energy to TOU windows."""
    out: list[tuple[float, float]] = []
    if len(series) < 2:
        return out
    prev_ts, prev_val = series[0]
    for ts, val in series[1:]:
        if val >= prev_val:
            delta = val - prev_val
        elif val < prev_val * 0.5:
            delta = val  # reset: new accumulation from 0
        else:
            delta = 0.0  # small dip / jitter
        if delta:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            out.append((dt.hour + dt.minute / 60.0, delta))
        prev_ts, prev_val = ts, val
    return out

"""Battery SoC projection (plan.md §6; task T062) — §21 critical logic.

Given forecast PV and forecast load per time-step, walk the battery's state of charge
forward: surplus (PV > load) charges it, deficit discharges it, each bounded by the
charge/discharge power limits and the usable SoC window; the grid makes up the rest.
Flags the times SoC is projected to hit empty (min) or full (max). Pure + unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BatterySpec:
    capacity_wh: float
    min_soc_pct: float = 10.0
    max_soc_pct: float = 100.0
    max_charge_w: float = 5000.0
    max_discharge_w: float = 5000.0

    @classmethod
    def from_dict(cls, d: dict) -> "BatterySpec":
        return cls(
            capacity_wh=float(d.get("capacity_wh", 10000.0)),
            min_soc_pct=float(d.get("min_soc_pct", 10.0)),
            max_soc_pct=float(d.get("max_soc_pct", 100.0)),
            max_charge_w=float(d.get("max_charge_w", 5000.0)),
            max_discharge_w=float(d.get("max_discharge_w", 5000.0)),
        )


@dataclass(frozen=True, slots=True)
class SocPoint:
    ts: float
    soc_pct: float
    pv_w: float
    load_w: float
    battery_w: float   # +charge / −discharge (canonical sign)
    grid_w: float      # +import / −export

    def as_dict(self) -> dict:
        return {
            "ts": self.ts, "soc_pct": round(self.soc_pct, 1),
            "pv_w": round(self.pv_w, 1), "load_w": round(self.load_w, 1),
            "battery_w": round(self.battery_w, 1), "grid_w": round(self.grid_w, 1),
        }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def project_soc(
    start_soc_pct: float,
    hourly: list[tuple[float, float, float]],
    battery: BatterySpec,
    step_s: float = 3600.0,
) -> list[SocPoint]:
    """Project SoC across `hourly` = [(ts, pv_w, load_w)].

    For each step: net = pv − load. Surplus charges (capped by max_charge_w and headroom),
    deficit discharges (capped by max_discharge_w and available energy); whatever the
    battery can't source/absorb flows to/from the grid (+import / −export)."""
    min_wh = battery.min_soc_pct / 100.0 * battery.capacity_wh
    max_wh = battery.max_soc_pct / 100.0 * battery.capacity_wh
    soc_wh = _clamp(start_soc_pct / 100.0 * battery.capacity_wh, min_wh, max_wh)
    hours = step_s / 3600.0
    out: list[SocPoint] = []
    for ts, pv_w, load_w in hourly:
        net = pv_w - load_w
        if net >= 0:                                   # surplus → charge
            headroom_w = (max_wh - soc_wh) / hours
            batt_w = _clamp(net, 0.0, min(battery.max_charge_w, headroom_w))
        else:                                          # deficit → discharge
            available_w = (soc_wh - min_wh) / hours
            batt_w = -_clamp(-net, 0.0, min(battery.max_discharge_w, available_w))
        soc_wh = _clamp(soc_wh + batt_w * hours, min_wh, max_wh)
        grid_w = -(net - batt_w)                       # >0 import (deficit), <0 export (surplus)
        out.append(SocPoint(ts, soc_wh / battery.capacity_wh * 100.0, pv_w, load_w, batt_w, grid_w))
    return out


def first_time_at_or_below(points: list[SocPoint], soc_pct: float) -> float | None:
    """Timestamp SoC is first projected to fall to/under `soc_pct` (depletion), or None."""
    for p in points:
        if p.soc_pct <= soc_pct + 1e-9:
            return p.ts
    return None


def first_time_at_or_above(points: list[SocPoint], soc_pct: float) -> float | None:
    """Timestamp SoC is first projected to reach/exceed `soc_pct` (full), or None."""
    for p in points:
        if p.soc_pct >= soc_pct - 1e-9:
            return p.ts
    return None

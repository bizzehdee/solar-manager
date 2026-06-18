"""Economic + efficiency derivations (plan.md §3, §19; task T052) — §21 critical logic.

Pure functions over already-computed energy totals (Wh) + a tariff. Kept separate from
the stats orchestration so the money/CO₂/ROI math is unit-tested in isolation.

Conventions: energy in Wh, rates currency-per-kWh, carbon intensity gCO₂/kWh.
"""

from __future__ import annotations

from dataclasses import dataclass


def round_trip_efficiency(charge_wh: float, discharge_wh: float) -> float | None:
    """Battery round-trip efficiency = energy out / energy in (0..1). None if not charged."""
    if charge_wh <= 0:
        return None
    return discharge_wh / charge_wh


def self_consumed_pv_wh(pv_wh: float, export_wh: float) -> float:
    """PV generated that was used on-site rather than exported (≥ 0)."""
    return max(0.0, pv_wh - export_wh)


@dataclass(frozen=True, slots=True)
class Economics:
    import_cost: float        # what was paid for grid import (energy only)
    export_revenue: float     # feed-in revenue for exported energy
    net_cost: float           # what the period actually cost: import - export + standing charge
    baseline_cost: float      # what it would have cost with NO solar/battery (incl. standing charge)
    savings: float            # baseline_cost - net_cost (standing charge cancels — solar can't avoid it)
    co2_avoided_kg: float     # CO₂ not emitted thanks to PV displacing grid
    standing_charge: float = 0.0  # the fixed daily charge folded into net & baseline (shown for transparency)

    def as_dict(self) -> dict:
        return {
            "import_cost": round(self.import_cost, 4),
            "export_revenue": round(self.export_revenue, 4),
            "standing_charge": round(self.standing_charge, 4),
            "net_cost": round(self.net_cost, 4),
            "baseline_cost": round(self.baseline_cost, 4),
            "savings": round(self.savings, 4),
            "co2_avoided_kg": round(self.co2_avoided_kg, 4),
        }


def compute_economics(
    *,
    import_cost: float,
    export_revenue: float,
    baseline_cost: float,
    pv_wh: float,
    export_wh: float,
    co2_intensity_g_per_kwh: float,
    standing_charge: float = 0.0,
) -> Economics:
    """Bring the priced flows together into the headline economics.

    - net_cost = what you actually paid: import − export + the fixed standing charge.
    - baseline_cost = the bill with no PV/battery: every kWh of load bought from the grid
      (priced at the import schedule by the caller, so TOU is respected) + the same standing
      charge (you pay it either way).
    - savings = baseline_cost − net_cost. The standing charge is in *both*, so it cancels —
      solar can't save you a fixed daily charge — but it's surfaced for a truthful bill total.
    - CO₂ avoided = on-site-consumed PV (kWh) × grid carbon intensity (it displaced grid).
    """
    net_cost = import_cost - export_revenue + standing_charge
    baseline_total = baseline_cost + standing_charge
    self_consumed_kwh = self_consumed_pv_wh(pv_wh, export_wh) / 1000.0
    co2_avoided = self_consumed_kwh * co2_intensity_g_per_kwh / 1000.0  # g → kg
    return Economics(
        import_cost=import_cost,
        export_revenue=export_revenue,
        net_cost=net_cost,
        baseline_cost=baseline_total,
        savings=baseline_total - net_cost,
        co2_avoided_kg=co2_avoided,
        standing_charge=standing_charge,
    )


def payback_years(system_cost: float, annual_savings: float) -> float | None:
    """Simple payback period in years. None when savings are non-positive (never pays back)."""
    if annual_savings <= 0:
        return None
    return system_cost / annual_savings


def roi_percent(system_cost: float, annual_savings: float, years: float) -> float | None:
    """Return on investment over `years`, as a percentage of the system cost. None if the
    system is free (undefined)."""
    if system_cost <= 0:
        return None
    return (annual_savings * years - system_cost) / system_cost * 100.0

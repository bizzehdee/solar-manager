"""Automation planning engine — pure, suggest-only (plan.md §18; task L03a).

Given the import tariff (§5), the battery, the current SoC, the inverter's current work-mode
timer slots, and tomorrow's expected PV / load energy (§6 forecast), propose timer-slot
changes that cut cost by **arbitraging** the battery: force a grid-charge in the cheapest
import window up to a *forecast-aware* target SoC, then reserve the battery for the expensive
(peak) hours. The richer the solar forecast, the less we top up from the grid overnight.

This module is deliberately **pure** — no DB, no clock, no device, no writes. It takes plain
data and returns a plan; wiring it to the live forecast/tariff/device and (much later, opt-in)
to the §12 write path is done by separate deliverables (L03b/L03d). That keeps the decision
logic — a §21 critical-logic surface — unit-testable in isolation with known vectors.

Sign/unit conventions follow the canonical vocabulary (§4): SoC in percent, energy in Wh,
power in W, rates in currency-per-kWh. Timer-slot field keys match the profile's `timer_slots`
settings section (`start_time`/`power_w`/`target_soc_pct`/`charge_from_grid`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..forecast.battery import BatterySpec
from ..tariff import RateSchedule


@dataclass(frozen=True, slots=True)
class AutomationStrategy:
    """Tunables for the cost-arbitrage strategy. Conservative defaults; all overridable."""

    name: str = "cost_arbitrage"
    # Battery SoC band the plan is allowed to drive to.
    max_target_soc_pct: float = 100.0
    # Floor to keep during the day so the battery still covers the evening peak.
    day_reserve_soc_pct: float = 20.0
    # Don't bother arbitraging when the cheap→peak spread is below this (currency/kWh):
    # the wear/round-trip loss isn't worth a few pence.
    min_rate_spread: float = 0.05
    # Round proposed target SoC to this step (inverters take integer percent anyway).
    soc_step_pct: float = 5.0


@dataclass(frozen=True, slots=True)
class SlotChange:
    """A proposed change to one work-mode timer slot, with the reason it's proposed."""

    index: int
    fields: dict[str, Any]
    reason: str


@dataclass(frozen=True, slots=True)
class AutomationPlan:
    """The planner's output. `action` is False when nothing is worth changing (the `summary`
    says why); otherwise `changes` lists per-slot proposals and `estimated_saving` is a
    first-order daily figure in the tariff's currency units."""

    strategy: str
    action: bool
    summary: str
    changes: list[SlotChange] = field(default_factory=list)
    estimated_saving: float = 0.0
    inputs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "action": self.action,
            "summary": self.summary,
            "changes": [{"index": c.index, "fields": c.fields, "reason": c.reason} for c in self.changes],
            "estimated_saving": round(self.estimated_saving, 4),
            "inputs": self.inputs,
        }


def _hourly_rates(schedule: RateSchedule) -> list[float]:
    """Import rate for each hour-of-day, sampled at the half-hour (avoids window-edge
    ambiguity since windows are half-open [start, end))."""
    return [schedule.rate_at(h + 0.5) for h in range(24)]


def _contiguous_window_around(rates: list[float], target: float) -> tuple[int, int, float]:
    """The maximal run of consecutive hours whose rate equals `target`, allowing a single
    wrap across midnight. Returns (start_hour, end_hour, rate) with end exclusive (end may be
    ≤ start when the run wraps, e.g. 23→6)."""
    hours_at = [h for h in range(24) if rates[h] == target]
    # Build runs over a doubled timeline so a midnight-wrapping run is contiguous.
    flags = [rates[h % 24] == target for h in range(48)]
    best_start, best_len = hours_at[0], 1
    h = 0
    while h < 48:
        if flags[h]:
            start = h
            while h < 48 and flags[h]:
                h += 1
            run_len = h - start
            if run_len > best_len and run_len <= 24:
                best_start, best_len = start % 24, run_len
        else:
            h += 1
    end = (best_start + best_len) % 24
    return best_start, end, target


def cheapest_window(schedule: RateSchedule) -> tuple[int, int, float]:
    """The contiguous block of hours at the lowest import rate (the place to grid-charge).
    end is exclusive and may wrap midnight."""
    rates = _hourly_rates(schedule)
    return _contiguous_window_around(rates, min(rates))


def peak_window(schedule: RateSchedule) -> tuple[int, int, float]:
    """The contiguous block of hours at the highest import rate (the place to discharge)."""
    rates = _hourly_rates(schedule)
    return _contiguous_window_around(rates, max(rates))


def overnight_target_soc_pct(
    expected_pv_wh: float,
    expected_load_wh: float,
    battery: BatterySpec,
    strategy: AutomationStrategy = AutomationStrategy(),
) -> float:
    """How full to charge the battery in the cheap window, given tomorrow's outlook.

    We need the battery to carry the day's energy *deficit* (load the sun won't cover) on top
    of the day reserve. A surplus (sunny) day needs only the reserve; a poor day charges toward
    full. Result is clamped to the battery's SoC band and the strategy ceiling, then rounded."""
    deficit_wh = max(0.0, expected_load_wh - expected_pv_wh)
    capacity = battery.capacity_wh or 1.0
    deficit_pct = deficit_wh / capacity * 100.0
    raw = strategy.day_reserve_soc_pct + deficit_pct
    ceiling = min(strategy.max_target_soc_pct, battery.max_soc_pct)
    floor = max(strategy.day_reserve_soc_pct, battery.min_soc_pct)
    clamped = max(floor, min(ceiling, raw))
    step = strategy.soc_step_pct or 1.0
    return round(round(clamped / step) * step, 2)


def _slot_view(slots: Sequence[Mapping[str, Any]], index: int) -> dict[str, Any]:
    return dict(slots[index]) if 0 <= index < len(slots) else {}


def plan_timer(
    current_slots: Sequence[Mapping[str, Any]],
    import_schedule: RateSchedule,
    battery: BatterySpec,
    current_soc_pct: float,
    expected_pv_wh: float,
    expected_load_wh: float,
    *,
    strategy: AutomationStrategy = AutomationStrategy(),
) -> AutomationPlan:
    """Propose work-mode timer changes for the cost-arbitrage strategy.

    Plan: slot 0 → grid-charge from the start of the cheapest window up to a forecast-aware
    target SoC; slot 1 → from the start of the peak window, self-use down to the day reserve
    (no grid charge), so the cheaply-stored energy covers the expensive hours. Returns
    `action=False` (with a reason) when there's nothing worth doing — e.g. a flat tariff, too
    small a price spread, or the target equals the reserve (no headroom to arbitrage)."""
    rates = _hourly_rates(import_schedule)
    low, high = min(rates), max(rates)
    spread = high - low

    inputs = {
        "current_soc_pct": round(current_soc_pct, 1),
        "expected_pv_wh": round(expected_pv_wh, 1),
        "expected_load_wh": round(expected_load_wh, 1),
        "cheapest_rate": round(low, 4),
        "peak_rate": round(high, 4),
        "rate_spread": round(spread, 4),
    }

    if spread <= 0.0:
        return AutomationPlan(strategy.name, False, "Flat import tariff — no cheap window to arbitrage.", inputs=inputs)
    if spread < strategy.min_rate_spread:
        return AutomationPlan(
            strategy.name,
            False,
            f"Price spread {spread:.3f}/kWh below the {strategy.min_rate_spread:.3f} threshold — not worth arbitraging.",
            inputs=inputs,
        )

    cheap_start, cheap_end, cheap_rate = cheapest_window(import_schedule)
    peak_start, peak_end, peak_rate = peak_window(import_schedule)
    target_soc = overnight_target_soc_pct(expected_pv_wh, expected_load_wh, battery, strategy)
    reserve_soc = max(strategy.day_reserve_soc_pct, battery.min_soc_pct)
    inputs.update({
        "cheap_window": [cheap_start, cheap_end],
        "peak_window": [peak_start, peak_end],
        "target_soc_pct": target_soc,
        "reserve_soc_pct": round(reserve_soc, 1),
    })

    if target_soc <= reserve_soc:
        return AutomationPlan(
            strategy.name,
            False,
            "Tomorrow's solar covers the load — no overnight grid-charge needed beyond the reserve.",
            inputs=inputs,
        )

    charge_slot = {
        "start_time": f"{cheap_start:02d}:00",
        "charge_from_grid": True,
        "target_soc_pct": int(round(target_soc)),
        "power_w": int(battery.max_charge_w),
    }
    reserve_slot = {
        "start_time": f"{peak_start:02d}:00",
        "charge_from_grid": False,
        "target_soc_pct": int(round(reserve_soc)),
        "power_w": int(battery.max_discharge_w),
    }

    changes: list[SlotChange] = []
    if _slot_view(current_slots, 0) != {**_slot_view(current_slots, 0), **charge_slot}:
        changes.append(SlotChange(
            0, charge_slot,
            f"Grid-charge to {charge_slot['target_soc_pct']}% from {charge_slot['start_time']} "
            f"in the cheap window ({cheap_rate:.3f}/kWh).",
        ))
    if _slot_view(current_slots, 1) != {**_slot_view(current_slots, 1), **reserve_slot}:
        changes.append(SlotChange(
            1, reserve_slot,
            f"Self-use down to {reserve_slot['target_soc_pct']}% from {reserve_slot['start_time']} "
            f"to cover the peak ({peak_rate:.3f}/kWh) from the battery.",
        ))

    if not changes:
        return AutomationPlan(strategy.name, False, "Timer already matches the optimal plan.", inputs=inputs)

    # First-order saving: the energy we add overnight and discharge during peak, valued at the
    # cheap→peak spread. Bounded by both the charge headroom and the peak-hours load.
    headroom_pct = max(0.0, target_soc - current_soc_pct)
    charge_wh = headroom_pct / 100.0 * battery.capacity_wh
    peak_hours = (peak_end - peak_start) % 24 or 24
    peak_load_wh = expected_load_wh * (peak_hours / 24.0)
    shifted_wh = min(charge_wh, peak_load_wh)
    estimated_saving = shifted_wh / 1000.0 * spread

    summary = (
        f"Charge to {charge_slot['target_soc_pct']}% overnight at {cheap_rate:.3f}/kWh and "
        f"discharge through the {peak_rate:.3f}/kWh peak — est. saving {estimated_saving:.2f}/day."
    )
    return AutomationPlan(strategy.name, True, summary, changes=changes, estimated_saving=estimated_saving, inputs=inputs)

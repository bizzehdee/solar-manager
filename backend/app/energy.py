"""Energy accounting (plan.md §5, §10; task T046) — a §21 critical-logic module.

Two ways to turn instantaneous samples into energy (Wh), preferring the inverter's own
counters when present:

1. **Counter diffing** (`counter_to_wh`) — the inverter exposes cumulative daily/total
   energy counters (e.g. `today_pv_wh`). Summing positive deltas is exact and immune to
   missed samples, but must handle the **midnight reset** (daily counters drop to ~0) and
   occasional counter rollover/glitches.
2. **Power integration** (`integrate_wh`) — when no counter exists, integrate a power
   series over time (trapezoidal). Approximate, and sensitive to gaps, so we cap the gap
   any single trapezoid may span.

Both are pure functions of their inputs (no clock, no I/O) so they're tested hard with
known vectors. Energy that can't be derived is **absent, not zero** (plan.md §4).
"""

from __future__ import annotations

from collections.abc import Sequence

# A time/value point: (epoch_seconds, value).
Point = tuple[float, float]

# Don't bridge a trapezoid across a gap longer than this — a missing stretch of samples
# would otherwise invent energy. One hour covers hourly-rollup spacing and short sample
# outages; a genuine multi-hour gap contributes nothing rather than fabricating a flat run.
_MAX_GAP_S = 3600.0


def integrate_wh(points: Sequence[Point], *, max_gap_s: float = _MAX_GAP_S) -> float:
    """Trapezoidal integral of a power (W) series → energy (Wh).

    `points` is (epoch_seconds, power_w), assumed chronological. Gaps longer than
    `max_gap_s` are not bridged (each contributes nothing rather than a fabricated
    rectangle). Returns 0.0 for fewer than two points."""
    if len(points) < 2:
        return 0.0
    joules_like = 0.0  # actually watt-seconds; converted to Wh at the end
    for (t0, p0), (t1, p1) in zip(points, points[1:]):
        dt = t1 - t0
        if dt <= 0 or dt > max_gap_s:
            continue
        joules_like += (p0 + p1) / 2.0 * dt
    return joules_like / 3600.0


def counter_to_wh(readings: Sequence[Point], *, reset_factor: float = 0.5) -> float:
    """Energy from a monotonic-ish cumulative counter, summing only positive deltas.

    `readings` is (epoch_seconds, counter_value_wh), chronological. A **decrease** is
    treated as a reset (midnight rollover of a daily counter, or a power-cycle): the new
    value is taken as fresh accumulation from zero and added in full. To avoid a tiny dip
    (noise) being read as a reset, a drop only counts as a reset when the value falls below
    `reset_factor` of the previous reading; smaller dips contribute nothing.

    Returns the total Wh accumulated across the series (handling any number of resets)."""
    if len(readings) < 2:
        return 0.0
    total = 0.0
    prev = readings[0][1]
    for _, cur in readings[1:]:
        if cur >= prev:
            total += cur - prev               # normal forward accumulation
        elif cur < prev * reset_factor:
            total += cur                       # reset detected: new run starts from 0
        # else: small dip / jitter — ignore, don't subtract
        prev = cur
    return total


def self_consumption_wh(pv_wh: float, export_wh: float) -> float:
    """PV energy used on-site rather than exported. Clamped ≥ 0."""
    return max(0.0, pv_wh - export_wh)


def self_consumption_ratio(pv_wh: float, export_wh: float) -> float | None:
    """Fraction of generated PV consumed on-site (0..1). None when no PV (undefined)."""
    if pv_wh <= 0:
        return None
    return self_consumption_wh(pv_wh, export_wh) / pv_wh


def self_sufficiency_ratio(load_wh: float, import_wh: float) -> float | None:
    """Fraction of load met without grid import (0..1). None when no load (undefined)."""
    if load_wh <= 0:
        return None
    return max(0.0, load_wh - import_wh) / load_wh

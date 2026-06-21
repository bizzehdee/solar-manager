"""Derived (calculated) metrics — task L16-1.

These are computed from the canonical snapshot and merged into each `Reading.metrics` by the poller,
so they're indistinguishable from device metrics downstream: they appear in the live snapshot (cards,
gauges) and are persisted to `samples`/rollups (charts). They are "running today" figures derived
from the `today_*_wh` counters, so they evolve through the day.

Pure + dependency-free (just `economics` ratio helpers) so they're trivially unit-tested. Missing ≠
zero (§4): a metric is omitted when an input is absent/non-numeric or its denominator is 0 — never
faked to zero.
"""

from __future__ import annotations

from typing import Mapping

from . import economics
from .models import MetricValue

# The derived keys this module can produce (canonical; folded into metrics.ALL_METRICS).
DERIVED_METRICS = ("self_consumption_pct", "self_sufficiency_pct", "round_trip_efficiency_pct")


def _num(metrics: Mapping[str, MetricValue], key: str) -> float | None:
    """A metric as a float, or None if absent/non-numeric (bools excluded)."""
    v = metrics.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def derive_metrics(metrics: Mapping[str, MetricValue]) -> dict[str, float]:
    """Compute the derived metrics available from ``metrics``. Only keys whose inputs are present
    and whose denominator is > 0 are returned (so the caller can merge without faking absences)."""
    out: dict[str, float] = {}

    pv = _num(metrics, "today_pv_wh")
    export = _num(metrics, "today_grid_export_wh")
    if pv is not None and export is not None and pv > 0:
        out["self_consumption_pct"] = round(economics.self_consumed_pv_wh(pv, export) / pv * 100, 1)

    load = _num(metrics, "today_load_wh")
    grid_import = _num(metrics, "today_grid_import_wh")
    if load is not None and grid_import is not None and load > 0:
        self_supplied = max(0.0, load - grid_import)
        out["self_sufficiency_pct"] = round(self_supplied / load * 100, 1)

    charge = _num(metrics, "today_batt_charge_wh")
    discharge = _num(metrics, "today_batt_discharge_wh")
    rte = economics.round_trip_efficiency(charge, discharge) if charge is not None and discharge is not None else None
    if rte is not None:
        out["round_trip_efficiency_pct"] = round(rte * 100, 1)

    return out

"""Dashboard layouts (plan.md §8; task L06 / T_DB1).

A dashboard is a named 12-column grid of widgets. Two **builtins** (Now, History) are seeded
from code — they always exist, can't be deleted, and aren't writable through the API. Users can
create any number of their own, each stored as one JSON blob under the app-config key
`dashboard:<id>`. The stored JSON *is* the export/import wire format (`GET` to download, `PUT`
with a chosen id to import).

A widget is `{type, x, y, w, h, config}` on a 12-column grid; the frontend widget registry
(T_DB3) resolves `type` → component and reads `config`. The backend treats `config` as opaque.
"""

from __future__ import annotations

from typing import Any

KEY_PREFIX = "dashboard:"


def _widget(type_: str, x: int, y: int, w: int, h: int, config: dict | None = None) -> dict:
    return {"type": type_, "x": x, "y": y, "w": w, "h": h, "config": config or {}}


# ── Builtins (seeded from code, never the DB) ──────────────────────────────────────────
# "Now" — the live dashboard. Layout from the L06 spec (col×row; all 2×2 except energy-flow 6×6).
# Shorthand names map to widget-registry types + config: solar/load/battery/grid/battery-soc →
# metric-gauge (generic — pick a metric, override name/unit/full-scale); grid-v/grid-hz/today-solar
# → metric-card.
_NOW: dict[str, Any] = {
    "id": "now",
    "name": "Now",
    "builtin": True,
    "widgets": [
        _widget("energy-flow", 0, 0, 6, 6),
        _widget("metric-gauge", 6, 0, 2, 2, {"metric": "pv_power_w", "label": "Solar", "unit": "W", "max": 8000, "role": "warning"}),
        _widget("metric-gauge", 10, 0, 2, 2, {"metric": "load_power_w", "label": "Load", "unit": "W", "max": 8000, "role": "primary"}),
        _widget("metric-gauge", 6, 2, 2, 2, {"metric": "battery_soc_pct", "label": "Battery SoC", "unit": "%", "max": 100, "role": "success"}),
        _widget("metric-gauge", 8, 2, 2, 2, {"metric": "battery_power_w", "label": "Battery", "unit": "W", "max": 8000, "role": "success"}),
        _widget("metric-gauge", 10, 2, 2, 2, {"metric": "grid_power_w", "label": "Grid", "unit": "W", "max": 8000, "role": "info"}),
        _widget("metric-card", 6, 4, 2, 1, {"metric": "grid_voltage_v", "label": "Grid V", "unit": "V", "icon": "bi-lightning", "role": "info"}),
        _widget("metric-card", 8, 4, 2, 1, {"metric": "grid_frequency_hz", "label": "Grid Hz", "unit": "Hz", "icon": "bi-activity", "role": "info"}),
        _widget("metric-card", 10, 4, 2, 1, {"metric": "today_pv_wh", "label": "Today solar", "unit": "kWh", "icon": "bi-graph-up", "role": "warning"}),
        # Battery-health strip (each an individual metric-card; "—" when the metric isn't reported).
        _widget("metric-card", 0, 6, 3, 1, {"metric": "battery_soh_pct", "label": "State of Health", "unit": "%", "icon": "bi-heart-pulse", "role": "success"}),
        _widget("metric-card", 3, 6, 3, 1, {"metric": "battery_cycles", "label": "Cycles", "unit": "", "icon": "bi-arrow-repeat", "role": "secondary"}),
        _widget("metric-card", 6, 6, 3, 1, {"metric": "battery_temp_c", "label": "Battery temp", "unit": "°C", "icon": "bi-thermometer-half", "role": "danger"}),
        _widget("metric-card", 9, 6, 3, 1, {"metric": "battery_voltage_v", "label": "Battery voltage", "unit": "V", "icon": "bi-battery-half", "role": "info"}),
    ],
}

# "History" — the existing History page as a layout: today's derived-KPI row (daily-kpis) above an
# interactive metric/resolution/range time-series chart (history-chart). Both are container widgets
# that fetch their own data (stats/daily, history).
_HISTORY: dict[str, Any] = {
    "id": "history",
    "name": "History",
    "builtin": True,
    "widgets": [
        # Today's derived KPIs as individual metric-cards (the KPIs are first-class metrics now —
        # task L16). Units auto-fill from the metric suffix; savings has none (currency varies).
        _widget("metric-card", 0, 0, 2, 2, {"metric": "self_consumption_pct", "label": "Self-consumption", "icon": "bi-pie-chart", "role": "success"}),
        _widget("metric-card", 2, 0, 2, 2, {"metric": "self_sufficiency_pct", "label": "Self-sufficiency", "icon": "bi-house-check", "role": "primary"}),
        _widget("metric-card", 4, 0, 2, 2, {"metric": "savings", "label": "Savings today", "icon": "bi-piggy-bank", "role": "success"}),
        _widget("metric-card", 6, 0, 2, 2, {"metric": "co2_avoided_kg", "label": "CO₂ avoided", "icon": "bi-leaf", "role": "success"}),
        _widget("metric-card", 8, 0, 2, 2, {"metric": "peak_pv_w", "label": "Peak PV", "icon": "bi-sun", "role": "warning"}),
        _widget("metric-card", 10, 0, 2, 2, {"metric": "round_trip_efficiency_pct", "label": "Round-trip eff.", "icon": "bi-arrow-repeat", "role": "info"}),
        _widget("history-chart", 0, 2, 12, 6, {"metric": "pv_power_w", "resolution": "1h", "range": 1}),
    ],
}

BUILTINS: dict[str, dict] = {_NOW["id"]: _NOW, _HISTORY["id"]: _HISTORY}


class DashboardError(Exception):
    """Base for dashboard validation/protection errors."""


class DashboardNotFound(DashboardError):
    """Raised when an id matches neither a builtin nor a stored user dashboard."""


def _validate(dashboard_id: str, body: dict) -> dict:
    """Coerce/validate an incoming dashboard to the canonical shape. Raises ValueError on bad input."""
    if not isinstance(body, dict):
        raise ValueError("dashboard must be an object")
    name = str(body.get("name") or "").strip()
    if not name:
        raise ValueError("dashboard name is required")
    widgets_in = body.get("widgets", [])
    if not isinstance(widgets_in, list):
        raise ValueError("widgets must be a list")
    widgets: list[dict] = []
    for w in widgets_in:
        if not isinstance(w, dict) or not str(w.get("type") or "").strip():
            raise ValueError("each widget needs a type")
        config = w.get("config", {})
        if not isinstance(config, dict):
            raise ValueError("widget config must be an object")
        widgets.append(
            {
                "type": str(w["type"]),
                "x": int(w.get("x", 0)),
                "y": int(w.get("y", 0)),
                "w": int(w.get("w", 2)),
                "h": int(w.get("h", 2)),
                "config": config,
            }
        )
    return {"id": dashboard_id, "name": name, "builtin": False, "widgets": widgets}


class DashboardStore:
    """All dashboards live in app_config (one blob per `dashboard:<id>`) and are always read from
    there, so user edits persist. The Now/History **builtins are seeded into the DB from the code
    `BUILTINS` on first run**; the code seed is retained only as the **reset-to-default** target
    (delete on a builtin rewrites the seed rather than removing the row).
    """

    def __init__(self, app_config) -> None:
        self._cfg = app_config

    def _as_builtin(self, dashboard_id: str, stored: dict) -> dict:
        """A stored builtin keeps its builtin flag + canonical id regardless of what was saved."""
        return {**stored, "id": dashboard_id, "builtin": True}

    async def seed_builtins(self) -> None:
        """Write the code seed for each builtin into the DB if it isn't there yet (first run /
        new builtin in an upgrade). Never overwrites an existing (possibly user-edited) row."""
        for bid, seed in BUILTINS.items():
            if await self._cfg.get(KEY_PREFIX + bid, None) is None:
                await self._cfg.set(KEY_PREFIX + bid, {**seed})

    async def list(self) -> list[dict]:
        """Builtins first (in declaration order), then user dashboards by name — all from the DB,
        with the code seed as a defensive fallback if a builtin row is somehow absent."""
        stored = await self._cfg.list_prefix(KEY_PREFIX)
        result: list[dict] = []
        for bid, seed in BUILTINS.items():
            row = stored.get(KEY_PREFIX + bid)
            result.append(self._as_builtin(bid, row) if row else seed)
        users = [v for k, v in stored.items() if k[len(KEY_PREFIX):] not in BUILTINS]
        users.sort(key=lambda d: str(d.get("name", "")).lower())
        return result + users

    async def get(self, dashboard_id: str) -> dict:
        stored = await self._cfg.get(KEY_PREFIX + dashboard_id, None)
        if stored is not None:
            return self._as_builtin(dashboard_id, stored) if dashboard_id in BUILTINS else stored
        if dashboard_id in BUILTINS:
            return BUILTINS[dashboard_id]  # defensive: not seeded yet
        raise DashboardNotFound(dashboard_id)

    async def put(self, dashboard_id: str, body: dict) -> dict:
        """Create/replace a user dashboard, or save an edited builtin. Raises ValueError on a bad body."""
        dashboard = _validate(dashboard_id, body)
        if dashboard_id in BUILTINS:
            dashboard["builtin"] = True  # an edited builtin stays a builtin
        await self._cfg.set(KEY_PREFIX + dashboard_id, dashboard)
        return dashboard

    async def delete(self, dashboard_id: str) -> None:
        """User dashboard → remove it (404 if missing). Builtin → reset to the code seed (rewrite
        the DB row; the builtin is never removed)."""
        if dashboard_id in BUILTINS:
            await self._cfg.set(KEY_PREFIX + dashboard_id, {**BUILTINS[dashboard_id]})
            return
        if not await self._cfg.delete(KEY_PREFIX + dashboard_id):
            raise DashboardNotFound(dashboard_id)

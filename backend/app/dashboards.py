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
        _widget("metric-card", 6, 4, 2, 2, {"metric": "grid_voltage_v", "label": "Grid V", "unit": "V", "icon": "bi-lightning", "role": "info"}),
        _widget("metric-card", 8, 4, 2, 2, {"metric": "grid_frequency_hz", "label": "Grid Hz", "unit": "Hz", "icon": "bi-activity", "role": "info"}),
        _widget("metric-card", 10, 4, 2, 2, {"metric": "today_pv_wh", "label": "Today solar", "unit": "kWh", "icon": "bi-graph-up", "role": "warning"}),
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
        _widget("daily-kpis", 0, 0, 12, 2),
        _widget("history-chart", 0, 2, 12, 6, {"metric": "pv_power_w", "resolution": "1h", "range": 1}),
    ],
}

BUILTINS: dict[str, dict] = {_NOW["id"]: _NOW, _HISTORY["id"]: _HISTORY}


class DashboardError(Exception):
    """Base for dashboard validation/protection errors."""


class BuiltinProtected(DashboardError):
    """Raised when a write/delete targets a builtin dashboard."""


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
    """Builtins from code + user dashboards in app_config (one blob per `dashboard:<id>`)."""

    def __init__(self, app_config) -> None:
        self._cfg = app_config

    async def list(self) -> list[dict]:
        """All dashboards: builtins first (in declaration order), then user dashboards by name."""
        stored = await self._cfg.list_prefix(KEY_PREFIX)
        users = sorted(stored.values(), key=lambda d: str(d.get("name", "")).lower())
        return list(BUILTINS.values()) + users

    async def get(self, dashboard_id: str) -> dict:
        if dashboard_id in BUILTINS:
            return BUILTINS[dashboard_id]
        stored = await self._cfg.get(KEY_PREFIX + dashboard_id, None)
        if stored is None:
            raise DashboardNotFound(dashboard_id)
        return stored

    async def put(self, dashboard_id: str, body: dict) -> dict:
        """Create or replace a user dashboard. Raises BuiltinProtected for builtin ids,
        ValueError for an invalid body."""
        if dashboard_id in BUILTINS:
            raise BuiltinProtected(dashboard_id)
        dashboard = _validate(dashboard_id, body)
        await self._cfg.set(KEY_PREFIX + dashboard_id, dashboard)
        return dashboard

    async def delete(self, dashboard_id: str) -> None:
        if dashboard_id in BUILTINS:
            raise BuiltinProtected(dashboard_id)
        if not await self._cfg.delete(KEY_PREFIX + dashboard_id):
            raise DashboardNotFound(dashboard_id)

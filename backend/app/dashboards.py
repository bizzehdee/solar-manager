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
    """Builtins (seeded from code) + user dashboards, both overlaid by app_config (one blob per
    `dashboard:<id>`). A builtin id can carry a **personalised override** in app_config — it keeps
    its `builtin` flag and its code seed is preserved as the reset target (delete drops the override).
    """

    def __init__(self, app_config) -> None:
        self._cfg = app_config

    def _as_builtin(self, dashboard_id: str, stored: dict) -> dict:
        """A stored override for a builtin keeps the builtin flag + canonical id."""
        return {**stored, "id": dashboard_id, "builtin": True}

    async def list(self) -> list[dict]:
        """Builtins first (in declaration order; personalised override wins), then user dashboards by name."""
        stored = await self._cfg.list_prefix(KEY_PREFIX)
        result: list[dict] = []
        for bid, seed in BUILTINS.items():
            override = stored.get(KEY_PREFIX + bid)
            result.append(self._as_builtin(bid, override) if override else seed)
        users = [v for k, v in stored.items() if k[len(KEY_PREFIX):] not in BUILTINS]
        users.sort(key=lambda d: str(d.get("name", "")).lower())
        return result + users

    async def get(self, dashboard_id: str) -> dict:
        stored = await self._cfg.get(KEY_PREFIX + dashboard_id, None)
        if stored is not None:
            return self._as_builtin(dashboard_id, stored) if dashboard_id in BUILTINS else stored
        if dashboard_id in BUILTINS:
            return BUILTINS[dashboard_id]
        raise DashboardNotFound(dashboard_id)

    async def put(self, dashboard_id: str, body: dict) -> dict:
        """Create/replace a user dashboard, or store a personalised override for a builtin.
        Raises ValueError for an invalid body."""
        dashboard = _validate(dashboard_id, body)
        if dashboard_id in BUILTINS:
            dashboard["builtin"] = True  # personalised builtin stays a builtin
        await self._cfg.set(KEY_PREFIX + dashboard_id, dashboard)
        return dashboard

    async def delete(self, dashboard_id: str) -> None:
        """User dashboard → remove it (404 if missing). Builtin → reset: drop any personalised
        override (idempotent — the builtin itself is never removed)."""
        removed = await self._cfg.delete(KEY_PREFIX + dashboard_id)
        if not removed and dashboard_id not in BUILTINS:
            raise DashboardNotFound(dashboard_id)

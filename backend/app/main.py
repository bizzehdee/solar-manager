"""FastAPI application (plan.md §7 API surface, §13 deployment).

Surface: health, live (REST + WebSocket), **history** (Phase 2), and **device config CRUD**
(Phase 2) — all driven by the dummy inverter so the whole stack is usable with no hardware.
The poller feeds a persistence service that writes samples, rolls them up, and prunes; the
History API reads those rollups. The built Angular frontend is served by this same app in
production (one process, one port); in dev the Angular dev server proxies here.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from . import control
from .alerts import AlertRule
from .alerts.channels import SUPPORTED_CHANNELS, build_channels
from .alerts.engine import METRIC_FAULT_COUNT, METRIC_STALE_S
from .alerts.service import AlertService
from .automation.service import AutomationService
from .config import Settings
from .grid_events import GridEventService
from .integrations import ReadingsWebhookService
from .metrics import ALL_METRICS
from .devices.base import TransportError, system_clock
from .devices.factory import (
    build_device_from_config,
    build_registry_from_configs,
    default_device_configs,
)
from .devices.firmware import verify_firmware
from .devices.registry import DeviceRegistry
from .devices.serial_ports import list_serial_ports
from .devices.yaml_profile import available_profiles
from .forecast.openmeteo import OpenMeteoClient
from .forecast.service import ForecastService
from .persistence import PersistenceService
from .poller import Poller
from .stats import StatsService
from .storage.migrations import SCHEMA_VERSION
from .storage.repository import (
    AlertRepository,
    AppConfigRepository,
    AuditRepository,
    DeviceConfigRepository,
    SqliteHistoryRepository,
    open_repositories,
)
from .tariff import Tariff
from .version import __version__

# Where the built Angular app lands (Phase 0 frontend build output). Optional in dev.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "solarvolt" / "browser"


def _parse_time(value: str | None, default: float) -> float:
    """Parse a time query param: epoch seconds (float) or an ISO-8601 string. Naive ISO
    timestamps are read as UTC."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        pass
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


async def _seed_and_build_registry(
    config_repo: DeviceConfigRepository, settings: Settings, clock
) -> DeviceRegistry:
    """Build the registry from the config DB, seeding it with defaults on first run."""
    if await config_repo.count() == 0:
        for row in default_device_configs(settings):
            await config_repo.create(row)
    rows = await config_repo.list()
    return build_registry_from_configs(rows, clock=clock)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    clock = app.state.clock

    history_repo, config_repo, app_config, audit_repo, alert_repo = await open_repositories(settings.db_path)
    app.state.history_repo = history_repo
    app.state.config_repo = config_repo
    app.state.app_config = app_config
    app.state.audit_repo = audit_repo
    app.state.alert_repo = alert_repo
    app.state.stats = StatsService(history_repo, app_config)
    weather = app.state.weather or OpenMeteoClient()
    app.state.weather = weather
    app.state.forecast = ForecastService(history_repo, app_config, weather)

    if app.state.registry is None:
        app.state.registry = await _seed_and_build_registry(config_repo, settings, clock)
    registry: DeviceRegistry = app.state.registry

    await registry.connect_all()
    for device in registry.devices:
        await verify_firmware(device)

    poller = Poller(registry, interval_s=settings.poll_interval_s)
    app.state.poller = poller
    await poller.start()

    persistence = PersistenceService(
        history_repo,
        poller,
        persist_interval_s=settings.persist_interval_s,
        aggregate_interval_s=settings.aggregate_interval_s,
        retention_days=settings.history_retention_days,
    )
    app.state.persistence = persistence
    await persistence.start()

    alerts = AlertService(alert_repo, poller, app_config, interval_s=settings.alert_interval_s)
    app.state.alerts = alerts
    await alerts.start()

    grid_events = GridEventService(history_repo, poller, interval_s=settings.alert_interval_s, clock=clock)
    app.state.grid_events = grid_events
    await grid_events.start()

    readings_webhook = ReadingsWebhookService(poller, app_config)
    app.state.readings_webhook = readings_webhook
    await readings_webhook.start()

    automation = AutomationService(
        app_config, poller, registry, clock=clock,
        audit_repo=audit_repo, interval_s=settings.automation_interval_s,
    )
    app.state.automation = automation
    # Automation is always available (rules/preview need no flag). The scheduler *writes* inverter
    # registers, so it only runs under SOLARVOLT_ENABLE_CONTROL — the single gate on register writes.
    if settings.enable_control:
        await automation.start()
    try:
        yield
    finally:
        await automation.stop()
        await readings_webhook.stop()
        await grid_events.stop()
        await alerts.stop()
        await persistence.stop()
        await poller.stop()
        await registry.close_all()
        await history_repo.close()


def create_app(
    settings: Settings | None = None,
    registry: DeviceRegistry | None = None,
    *,
    clock=system_clock,
    weather: OpenMeteoClient | None = None,
) -> FastAPI:
    app = FastAPI(title="SolarVolt", version=__version__, lifespan=lifespan)
    app.state.settings = settings or Settings.from_env()
    app.state.registry = registry  # None => built from the config DB in lifespan
    app.state.clock = clock
    app.state.weather = weather  # None => real Open-Meteo client built in lifespan

    # ---- health / live (Phase 0) ----------------------------------------------
    @app.get("/api/health")
    async def health() -> JSONResponse:
        poller: Poller = app.state.poller
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "control_enabled": app.state.settings.enable_control,
                # Automation is always on; it can only *write* inverter registers under control (L03e-3).
                "automation_can_write": app.state.settings.enable_control,
                **poller.health(),
            }
        )

    @app.get("/api/diagnostics")
    async def diagnostics() -> JSONResponse:
        """Operational snapshot (plan.md §19 / T092): build/schema, DB size, rollup lag, and
        per-device online + Modbus comms stats."""
        poller: Poller = app.state.poller
        registry: DeviceRegistry = app.state.registry
        settings: Settings = app.state.settings
        history: SqliteHistoryRepository = app.state.history_repo

        db_size = None
        if settings.db_path and settings.db_path != ":memory:" and os.path.exists(settings.db_path):
            db_size = os.path.getsize(settings.db_path)

        watermark = await history.rollup_watermark()
        now_ts = app.state.clock().timestamp()
        health = {d["device_id"]: d for d in poller.health()["devices"]}
        devices = []
        for device in registry.devices:
            h = health.get(device.device_id, {})
            devices.append({
                "device_id": device.device_id,
                "vendor": device.info.vendor,
                "model": device.info.model,
                "online": h.get("online", False),
                "last_sample_age_s": h.get("last_sample_age_s"),
                "comms": device.comms_stats(),
            })
        return JSONResponse({
            "version": __version__,
            "schema_version": SCHEMA_VERSION,
            "control_enabled": settings.enable_control,
            "poll_interval_s": settings.poll_interval_s,
            "database": {"path": settings.db_path, "size_bytes": db_size},
            "rollup": {
                "watermark_ts": watermark or None,
                "lag_s": round(now_ts - watermark, 1) if watermark else None,
            },
            "alerts": {"active_count": await app.state.alert_repo.active_count()},
            "devices": devices,
        })

    @app.get("/api/live")
    async def live() -> JSONResponse:
        poller: Poller = app.state.poller
        await poller.ensure_polled()
        return JSONResponse(poller.snapshot())

    @app.websocket("/ws/live")
    async def ws_live(ws: WebSocket) -> None:
        poller: Poller = app.state.poller
        await ws.accept()
        await poller.ensure_polled()
        queue = poller.subscribe()
        try:
            await ws.send_json(poller.snapshot())
            while True:
                snap = await queue.get()
                await ws.send_json(snap)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            poller.unsubscribe(queue)

    # ---- history (Phase 2, T044) ----------------------------------------------
    def _default_device_id() -> str | None:
        registry: DeviceRegistry = app.state.registry
        devices = registry.devices
        return devices[0].device_id if devices else None

    @app.get("/api/history/metrics")
    async def history_metrics(device_id: str | None = None) -> JSONResponse:
        repo: SqliteHistoryRepository = app.state.history_repo
        device_id = device_id or _default_device_id()
        metrics = await repo.metrics(device_id) if device_id else []
        return JSONResponse({"device_id": device_id, "metrics": metrics})

    @app.get("/api/history")
    async def history(
        metric: str = Query(...),
        device_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        resolution: str = "raw",
    ) -> JSONResponse:
        repo: SqliteHistoryRepository = app.state.history_repo
        device_id = device_id or _default_device_id()
        now = datetime.now(timezone.utc).timestamp()
        end_ts = _parse_time(end, now)
        start_ts = _parse_time(start, end_ts - 86400.0)
        try:
            points = await repo.query(device_id, metric, start_ts, end_ts, resolution)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(
            {
                "device_id": device_id,
                "metric": metric,
                "resolution": resolution,
                "start": start_ts,
                "end": end_ts,
                "points": [p.as_dict() for p in points],
            }
        )

    # ---- backup / restore / export (Phase 8 / T091) ---------------------------
    @app.get("/api/backup")
    async def backup() -> Response:
        history: SqliteHistoryRepository = app.state.history_repo
        data = await history.backup_bytes()
        return Response(
            data, media_type="application/x-sqlite3",
            headers={"Content-Disposition": "attachment; filename=solarvolt-backup.sqlite"},
        )

    @app.post("/api/restore")
    async def restore(file: UploadFile = File(...)) -> JSONResponse:
        data = await file.read()
        if not _valid_solarvolt_db(data):
            raise HTTPException(status_code=422, detail="not a valid SolarVolt database backup")
        history: SqliteHistoryRepository = app.state.history_repo
        try:
            await history.restore(data)
        except ValueError as exc:  # e.g. in-memory DB can't be restored
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "bytes": len(data)})

    @app.get("/api/export")
    async def export_csv(
        metric: str = Query(...), device_id: str | None = None,
        start: str | None = None, end: str | None = None, resolution: str = "raw",
    ) -> Response:
        import csv
        import io

        repo: SqliteHistoryRepository = app.state.history_repo
        device_id = device_id or _default_device_id()
        now = datetime.now(timezone.utc).timestamp()
        end_ts = _parse_time(end, now)
        start_ts = _parse_time(start, end_ts - 86400.0)
        try:
            points = await repo.query(device_id, metric, start_ts, end_ts, resolution)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts", "iso", "value", "min", "max", "last", "n"])
        for p in points:
            d = p.as_dict()
            iso = datetime.fromtimestamp(d["ts"], tz=timezone.utc).isoformat()
            w.writerow([d["ts"], iso, d["value"], d.get("min", ""), d.get("max", ""), d.get("last", ""), d.get("n", "")])
        fname = f"{device_id}-{metric}-{resolution}.csv"
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})

    # ---- statistics (Phase 3, T050/T052/T053) ---------------------------------
    @app.get("/api/stats/daily")
    async def stats_daily(device_id: str | None = None, date: str | None = None) -> JSONResponse:
        stats: StatsService = app.state.stats
        device_id = device_id or _default_device_id()
        now = datetime.now(timezone.utc).timestamp()
        day = _parse_time(date, now)
        result = await stats.daily(device_id, day)
        return JSONResponse(result.as_dict())

    @app.get("/api/stats/config")
    async def get_stats_config() -> JSONResponse:
        cfg: AppConfigRepository = app.state.app_config
        tariff = await cfg.get("tariff", {})
        econ = await cfg.get("economics", {})
        return JSONResponse({"tariff": tariff or Tariff().to_dict(), "economics": econ or {}})

    @app.put("/api/stats/config")
    async def put_stats_config(body: dict = Body(...)) -> JSONResponse:
        cfg: AppConfigRepository = app.state.app_config
        if "tariff" in body:
            # Validate by round-tripping through the model (rejects malformed shapes).
            try:
                tariff = Tariff.from_dict(body["tariff"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"invalid tariff: {exc}") from exc
            await cfg.set("tariff", tariff.to_dict())
        if "economics" in body:
            await cfg.set("economics", body["economics"])
        return await get_stats_config()

    # ---- forecast (Phase 4, T063/T064) ----------------------------------------
    @app.get("/api/forecast")
    async def forecast(device_id: str | None = None, days: int = Query(7, ge=1, le=7)) -> JSONResponse:
        svc: ForecastService = app.state.forecast
        device_id = device_id or _default_device_id()
        return JSONResponse(await svc.forecast(device_id, days))

    @app.get("/api/forecast/config")
    async def get_forecast_config() -> JSONResponse:
        svc: ForecastService = app.state.forecast
        return JSONResponse(await svc.config())

    @app.put("/api/forecast/config")
    async def put_forecast_config(body: dict = Body(...)) -> JSONResponse:
        cfg: AppConfigRepository = app.state.app_config
        for key in ("site", "arrays", "battery"):
            if key in body:
                await cfg.set(key, body[key])
        svc: ForecastService = app.state.forecast
        return JSONResponse(await svc.config())

    # ---- formatting preferences (Phase 8 / T093) ------------------------------
    @app.get("/api/preferences")
    async def get_preferences() -> JSONResponse:
        cfg: AppConfigRepository = app.state.app_config
        prefs = await cfg.get("preferences", None) or {"locale": "en-US"}
        return JSONResponse(prefs)

    @app.put("/api/preferences")
    async def put_preferences(body: dict = Body(...)) -> JSONResponse:
        cfg: AppConfigRepository = app.state.app_config
        # Persist a small allow-list of display preferences (English ships first).
        prefs = {k: body[k] for k in ("locale", "currency", "timezone") if k in body}
        await cfg.set("preferences", prefs)
        return JSONResponse(prefs)

    @app.get("/api/forecast/calibrate")
    async def calibrate_forecast(device_id: str | None = None) -> JSONResponse:
        svc: ForecastService = app.state.forecast
        return JSONResponse(await svc.calibrate(device_id or _default_device_id()))

    # ---- device config CRUD (Phase 2, T047) -----------------------------------
    def _device_status(row: dict) -> dict:
        registry: DeviceRegistry = app.state.registry
        poller: Poller = getattr(app.state, "poller", None)
        device = registry.get(row["id"])
        health = poller.health() if poller else {"devices": []}
        live = next((d for d in health["devices"] if d["device_id"] == row["id"]), None)
        return {
            **row,
            "online": bool(live and live["online"]),
            "last_sample_age_s": live["last_sample_age_s"] if live else None,
            "capabilities": sorted(device.capabilities()) if device else [],
            "ratings": (device.info.ratings or {}) if device else {},  # ac_power_w etc. (gauge scales)
            "settings": bool(device and device.has_settings),  # read-only display available (Phase 5)
            # Editable only when the deploy flag is on AND the device is writable (Phase 6).
            "control": app.state.settings.enable_control and bool(device and device.is_writable),
        }

    def _require_device(device_id: str):
        device = app.state.registry.get(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail=f"device {device_id!r} not found")
        return device

    # ---- device settings (read-only, Phase 5 / T071; UNGATED — reading is monitoring) ----
    @app.get("/api/devices/{device_id}/settings/schema")
    async def device_settings_schema(device_id: str) -> JSONResponse:
        device = _require_device(device_id)
        schema = device.settings_schema()
        return JSONResponse({
            "device_id": device_id,
            "supported": schema is not None,
            "sections": schema.as_dict()["sections"] if schema else [],
        })

    @app.get("/api/devices/{device_id}/settings")
    async def device_settings(device_id: str) -> JSONResponse:
        device = _require_device(device_id)
        values = await device.read_settings()
        etag = control.settings_etag(values) if values is not None else None
        headers = {"ETag": etag} if etag else None
        info = device.info
        return JSONResponse(
            {
                "device_id": device_id,
                "supported": values is not None,
                "control_enabled": app.state.settings.enable_control and device.is_writable,
                "etag": etag,
                "info": {
                    "vendor": info.vendor,
                    "model": info.model,
                    "serial": info.serial,
                    "firmware": info.firmware,
                },
                "values": values or {},
            },
            headers=headers,
        )

    # ---- settings write (Phase 6 / T076; GATED behind SOLARVOLT_ENABLE_CONTROL) ----
    @app.put("/api/devices/{device_id}/settings")
    async def write_device_settings(device_id: str, request: Request, body: dict = Body(...)) -> JSONResponse:
        if not app.state.settings.enable_control:
            # Write-back is a deploy decision; off ⇒ the endpoint doesn't function (§12).
            raise HTTPException(status_code=403, detail="control is disabled (SOLARVOLT_ENABLE_CONTROL is off)")
        device = _require_device(device_id)
        section = body.get("section")
        values = body.get("values")
        index = body.get("index")
        if not isinstance(section, str) or not section:
            raise HTTPException(status_code=422, detail="body needs a 'section' and 'values'")
        # If-Match header (preferred) or body etag — optimistic concurrency (§12 rule 5).
        if_match = request.headers.get("If-Match") or body.get("etag")

        try:
            result = await control.apply_settings(device, section, values, index=index, if_match=if_match)
        except control.SettingsValidationError as exc:
            raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc
        except control.StaleSettingsError as exc:
            raise HTTPException(
                status_code=412, detail={"error": str(exc), "current_etag": exc.current_etag}
            ) from exc
        except control.NotWritableError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc), "addrs": exc.addrs}) from exc
        except TransportError as exc:
            await _audit(app, device_id, section, index, {}, "error", request)
            raise HTTPException(status_code=502, detail=f"write failed on the device: {exc}") from exc
        except control.SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await _audit(app, device_id, section, index, result.changes, "ok" if result.ok else "mismatch", request)
        payload = {
            "device_id": device_id,
            "ok": result.ok,
            "section": section,
            "index": index,
            "changes": result.changes,
            "mismatches": result.mismatches,
            "etag": result.etag,
            "values": result.after,
        }
        # Read-back mismatch ⇒ NOT success: surface as a conflict with the rollback info (§12 rule 4).
        status = 200 if result.ok else 409
        return JSONResponse(payload, status_code=status, headers={"ETag": result.etag})

    @app.get("/api/audit")
    async def list_audit(device_id: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> JSONResponse:
        repo: AuditRepository = app.state.audit_repo
        return JSONResponse({"entries": await repo.list(device_id=device_id, limit=limit)})

    @app.get("/api/grid-events")
    async def list_grid_events(limit: int = Query(100, ge=1, le=1000)) -> JSONResponse:
        repo: SqliteHistoryRepository = app.state.history_repo
        return JSONResponse({"events": await repo.list_grid_events(limit=limit)})

    # ---- alerts (Phase 7 / T082) ----------------------------------------------
    @app.get("/api/alerts")
    async def list_alerts(active: bool = False, limit: int = Query(100, ge=1, le=1000)) -> JSONResponse:
        repo: AlertRepository = app.state.alert_repo
        return JSONResponse({
            "alerts": await repo.list_alerts(active_only=active, limit=limit),
            "active_count": await repo.active_count(),
        })

    @app.post("/api/alerts/{alert_id}/ack")
    async def ack_alert(alert_id: int) -> JSONResponse:
        repo: AlertRepository = app.state.alert_repo
        if not await repo.ack(alert_id, app.state.clock().timestamp()):
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        return JSONResponse({"ok": True})

    @app.post("/api/alerts/{alert_id}/snooze")
    async def snooze_alert(alert_id: int, body: dict = Body(default={})) -> JSONResponse:
        repo: AlertRepository = app.state.alert_repo
        minutes = float(body.get("minutes", 60))
        until = app.state.clock().timestamp() + minutes * 60.0
        if not await repo.snooze(alert_id, until):
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        return JSONResponse({"ok": True, "snooze_until": until})

    @app.get("/api/alert-rules")
    async def list_alert_rules() -> JSONResponse:
        repo: AlertRepository = app.state.alert_repo
        return JSONResponse({"rules": await repo.list_rules()})

    @app.get("/api/alert-rules/options")
    async def alert_rule_options() -> JSONResponse:
        """Field choices for the rule-editor UI (L11): selectable metrics (the canonical
        vocabulary plus the two synthetic keys the engine resolves specially), comparison
        operators, severities, and the configured notification channels."""
        cfg = await app.state.app_config.get("alert_channels", {}) or {}
        return JSONResponse({
            "metrics": sorted(ALL_METRICS) + [METRIC_STALE_S, METRIC_FAULT_COUNT],
            "ops": ["lt", "le", "gt", "ge", "eq", "ne"],
            "severities": ["info", "warning", "critical"],
            # Only offer channels that are actually configured (in-app inbox is always recorded).
            "channels": list(build_channels(cfg).keys()),
        })

    # ---- notification channels (Later / L10) ----------------------------------
    async def _alert_channels_view() -> dict:
        cfg = await app.state.app_config.get("alert_channels", {}) or {}
        return {
            "channels": cfg,
            "configured": list(build_channels(cfg).keys()),
            "supported": list(SUPPORTED_CHANNELS),
        }

    @app.get("/api/alert-channels")
    async def get_alert_channels() -> JSONResponse:
        """Notification-channel config (webhook/email/Telegram/ntfy/Gotify/Pushover) + which are
        fully configured. Single-house, no-auth deployment (CLAUDE.md) — secrets are returned for
        editing, as the whole DB is already user-downloadable via /api/backup."""
        return JSONResponse(await _alert_channels_view())

    @app.put("/api/alert-channels")
    async def put_alert_channels(body: dict = Body(...)) -> JSONResponse:
        cfg = {k: v for k, v in (body or {}).items() if k in SUPPORTED_CHANNELS and isinstance(v, dict)}
        await app.state.app_config.set("alert_channels", cfg)
        await app.state.alerts.reload()  # rebuild channels for the next dispatch
        return JSONResponse(await _alert_channels_view())

    @app.post("/api/alert-channels/{name}/test")
    async def test_alert_channel(name: str) -> JSONResponse:
        """Send a synthetic alert through one configured channel so the user can verify it."""
        channel = app.state.alerts._channels.get(name)
        if channel is None:
            raise HTTPException(status_code=400, detail=f"channel {name!r} is not configured")
        sample = {
            "rule_id": "_test_", "name": "SolarVolt test notification", "severity": "info",
            "metric": "battery_soc_pct", "value": 42, "message": "This is a test notification.",
            "device_id": None, "fired_at": app.state.clock().timestamp(),
        }
        try:
            await channel.send(sample)
        except Exception as exc:  # surface the failure to the manual caller
            raise HTTPException(status_code=502, detail=f"channel {name!r} failed: {exc}") from exc
        return JSONResponse({"ok": True})

    @app.put("/api/alert-rules/{rule_id}")
    async def put_alert_rule(rule_id: str, body: dict = Body(...)) -> JSONResponse:
        repo: AlertRepository = app.state.alert_repo
        body["id"] = rule_id
        try:
            rule = AlertRule.from_dict(body)  # validate by round-tripping the model
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid alert rule: {exc}") from exc
        await repo.upsert_rule(rule.to_dict())
        await app.state.alerts.reload()  # pick up the edit on the next tick
        return JSONResponse(rule.to_dict())

    @app.delete("/api/alert-rules/{rule_id}", status_code=204)
    async def delete_alert_rule(rule_id: str):
        repo: AlertRepository = app.state.alert_repo
        await repo.delete_rule(rule_id)
        app.state.alerts._engine.forget(rule_id)
        await app.state.alerts.reload()
        return JSONResponse(None, status_code=204)

    # ---- outbound readings webhook (Later / L09) ------------------------------
    def _readings_webhook_view(cfg: dict) -> dict:
        return {
            "url": cfg.get("url"),
            "interval_s": float(cfg.get("interval_s") or 60.0),
            "enabled": bool(cfg.get("enabled", False)),
        }

    @app.get("/api/integrations/readings-webhook")
    async def get_readings_webhook() -> JSONResponse:
        cfg = await app.state.app_config.get("readings_webhook", {}) or {}
        return JSONResponse(_readings_webhook_view(cfg))

    @app.put("/api/integrations/readings-webhook")
    async def put_readings_webhook(body: dict = Body(...)) -> JSONResponse:
        cfg = {
            "url": (str(body.get("url") or "").strip()) or None,
            "interval_s": max(float(body.get("interval_s", 60.0)), 5.0),
            "enabled": bool(body.get("enabled", False)),
        }
        await app.state.app_config.set("readings_webhook", cfg)
        return JSONResponse(_readings_webhook_view(cfg))

    @app.post("/api/integrations/readings-webhook/test")
    async def test_readings_webhook() -> JSONResponse:
        """Send one snapshot POST now and report the result, so the user can verify the URL
        without waiting for the next tick. Off the hot path — only the manual caller sees it."""
        cfg = await app.state.app_config.get("readings_webhook", {}) or {}
        url = cfg.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="no webhook URL configured")
        svc: ReadingsWebhookService = app.state.readings_webhook
        try:
            sent = await svc.post_once(url)
        except Exception as exc:  # surface the failure to the manual caller
            raise HTTPException(status_code=502, detail=f"webhook POST failed: {exc}") from exc
        return JSONResponse({"ok": True, "sent": sent})

    # ---- rule-based automation (Later / L03e) ---------------------------------
    # Always available (rules/preview/options need no flag). Only *applying* to the inverter
    # is gated, by SOLARVOLT_ENABLE_CONTROL — the single gate on register writes.
    def _automation_service() -> AutomationService:
        return app.state.automation

    @app.get("/api/automation/rules")
    async def list_automation_rules() -> JSONResponse:
        svc = _automation_service()
        return JSONResponse({"rules": await svc.list_rules()})

    @app.put("/api/automation/rules/{rule_id}")
    async def put_automation_rule(rule_id: str, body: dict = Body(...)) -> JSONResponse:
        svc = _automation_service()
        body["id"] = rule_id
        try:
            rule = await svc.upsert_rule(body)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid automation rule: {exc}") from exc
        return JSONResponse(rule)

    @app.delete("/api/automation/rules/{rule_id}", status_code=204)
    async def delete_automation_rule(rule_id: str):
        svc = _automation_service()
        if not await svc.delete_rule(rule_id):
            raise HTTPException(status_code=404, detail=f"automation rule {rule_id} not found")
        return JSONResponse(None, status_code=204)

    @app.get("/api/automation/options")
    async def automation_options(device_id: str | None = None) -> JSONResponse:
        svc = _automation_service()
        return JSONResponse(svc.options(device_id))

    @app.get("/api/automation/preview")
    async def automation_preview(device_id: str | None = None) -> JSONResponse:
        """What the rules would set right now (armed changes + previews). Never writes."""
        svc = _automation_service()
        return JSONResponse(await svc.preview(device_id))

    @app.post("/api/automation/apply")
    async def automation_apply(device_id: str | None = None) -> JSONResponse:
        """Apply now: write the armed, non-blocked winners through the §12 control flow. Gated by
        SOLARVOLT_ENABLE_CONTROL — like every path that touches inverter registers."""
        svc = _automation_service()
        if not app.state.settings.enable_control:
            raise HTTPException(status_code=403, detail="control is disabled (SOLARVOLT_ENABLE_CONTROL is off)")
        return JSONResponse(await svc.apply(device_id, source="automation:manual"))

    # ---- inverter clock sync (Phase 8 / T097) ---------------------------------
    @app.get("/api/devices/{device_id}/clock")
    async def device_clock(device_id: str) -> JSONResponse:
        device = _require_device(device_id)
        dt = await device.read_clock()
        system = app.state.clock()
        drift = (dt.timestamp() - system.timestamp()) if dt is not None else None
        return JSONResponse({
            "device_id": device_id,
            "supported": device.has_clock,
            "device_time": dt.isoformat() if dt is not None else None,
            "system_time": system.isoformat(),
            "drift_s": drift,
            # Correcting the clock is a write: needs the deploy flag AND confirmed RTC registers.
            "syncable": app.state.settings.enable_control and device.clock_syncable,
        })

    @app.post("/api/devices/{device_id}/clock/sync")
    async def sync_device_clock(device_id: str) -> JSONResponse:
        if not app.state.settings.enable_control:
            raise HTTPException(status_code=403, detail="control is disabled (SOLARVOLT_ENABLE_CONTROL is off)")
        device = _require_device(device_id)
        if not device.clock_syncable:
            raise HTTPException(status_code=400, detail="inverter clock is read-only (RTC registers unconfirmed)")
        system = app.state.clock()
        try:
            await device.sync_clock(system)
        except (TransportError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"clock sync failed: {exc}") from exc
        dt = await device.read_clock()
        drift = (dt.timestamp() - app.state.clock().timestamp()) if dt is not None else None
        return JSONResponse({"ok": True, "device_time": dt.isoformat() if dt else None, "drift_s": drift})

    # ---- Prometheus metrics (Phase 7 / T085) ----------------------------------
    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        poller: Poller = app.state.poller
        lines: list[str] = []
        for device_id, dev in poller.snapshot().get("devices", {}).items():
            for metric, value in dev.get("metrics", {}).items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue  # only numeric gauges
                name = f"solarvolt_{metric}"
                lines.append(f'{name}{{device="{device_id}"}} {value}')
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    # ---- device-setup helpers (populate the Add-device form; read-only discovery) ----
    @app.get("/api/serial-ports")
    async def serial_ports() -> JSONResponse:
        """Serial/tty devices present on the host, for the port dropdown."""
        return JSONResponse({"ports": list_serial_ports()})

    @app.get("/api/profiles")
    async def profiles() -> JSONResponse:
        """Selectable device profiles, for the profile dropdown."""
        return JSONResponse({"profiles": available_profiles()})

    @app.post("/api/devices/test")
    async def test_device(body: dict = Body(...)) -> JSONResponse:
        """Probe a prospective device's connection without persisting it: connect with
        the supplied transport/profile/params and attempt one read. Returns
        ``{ok, message}`` — a failed probe is a 200 with ``ok: false`` (the connection
        is bad, the request is fine)."""
        _validate_device_body(body, require_id=False)
        transport = body.get("transport", "dummy")
        if transport == "dummy":
            return JSONResponse({"ok": True, "message": "Dummy device — no hardware to test."})
        row = {**body, "id": body.get("id") or "__test__", "enabled": True}
        try:
            device = build_device_from_config(row, clock=app.state.clock)
        except FileNotFoundError:
            raise HTTPException(status_code=422, detail=f"unknown profile {body.get('profile')!r}")
        if device is None:
            raise HTTPException(status_code=422, detail="could not build a device to test")
        try:
            await device.connect()
            reading = await device.read()
        except TransportError as exc:
            return JSONResponse({"ok": False, "message": str(exc)})
        except Exception as exc:  # serial-open / decode errors surface as a failed probe
            return JSONResponse({"ok": False, "message": f"{type(exc).__name__}: {exc}"})
        finally:
            try:
                await device.close()
            except Exception:
                pass
        n = sum(1 for v in reading.metrics.values() if v is not None)
        return JSONResponse({"ok": True, "message": f"Connected — read {n} metric(s).", "metric_count": n})

    @app.get("/api/devices")
    async def list_devices() -> JSONResponse:
        repo: DeviceConfigRepository = app.state.config_repo
        rows = await repo.list()
        return JSONResponse({"devices": [_device_status(r) for r in rows]})

    @app.post("/api/devices", status_code=201)
    async def create_device(body: dict = Body(...)) -> JSONResponse:
        repo: DeviceConfigRepository = app.state.config_repo
        registry: DeviceRegistry = app.state.registry
        _validate_device_body(body, require_id=True)
        if await repo.get(body["id"]) is not None:
            raise HTTPException(status_code=409, detail=f"device {body['id']!r} already exists")
        row = await repo.create(body)
        await _add_to_registry(registry, row, app.state.clock)
        return JSONResponse(_device_status(row), status_code=201)

    @app.put("/api/devices/{device_id}")
    async def update_device(device_id: str, body: dict = Body(...)) -> JSONResponse:
        repo: DeviceConfigRepository = app.state.config_repo
        registry: DeviceRegistry = app.state.registry
        _validate_device_body(body, require_id=False)
        row = await repo.update(device_id, body)
        if row is None:
            raise HTTPException(status_code=404, detail=f"device {device_id!r} not found")
        await _remove_from_registry(registry, device_id)
        await _add_to_registry(registry, row, app.state.clock)
        return JSONResponse(_device_status(row))

    @app.delete("/api/devices/{device_id}", status_code=204)
    async def delete_device(device_id: str):
        repo: DeviceConfigRepository = app.state.config_repo
        registry: DeviceRegistry = app.state.registry
        if not await repo.delete(device_id):
            raise HTTPException(status_code=404, detail=f"device {device_id!r} not found")
        await _remove_from_registry(registry, device_id)
        return JSONResponse(None, status_code=204)

    # Serve the built frontend if present (production / packaged run). Harmless in dev.
    # /api and /ws routes are registered above, so they're matched before this mount;
    # everything else is either a static asset or a client-side route (SPA fallback).
    if _FRONTEND_DIST.is_dir():
        app.mount("/", SpaStaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")

    return app


class SpaStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for unmatched paths, so the Angular
    router's client-side routes (e.g. /now, /forecast) resolve on a hard refresh or
    bookmark when the backend serves the built UI. Real missing assets (a path with a
    file extension) still 404 rather than masquerading as the SPA shell."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                return await super().get_response("index.html", scope)
            raise


async def _audit(app, device_id, section, index, changes, result, request: Request) -> None:
    """Record one settings write to the audit log (§12 rule 6). Never blocks the response —
    an audit failure is logged, not surfaced (egress/side-effects off the hot path)."""
    repo: AuditRepository = getattr(app.state, "audit_repo", None)
    if repo is None:
        return
    source = request.client.host if request.client else ""
    ts = app.state.clock().timestamp()
    try:
        await repo.record(ts, device_id, section, changes, result, slot=index, source=source)
    except Exception as exc:  # pragma: no cover - audit must never break a write response
        logging.getLogger("solarvolt").warning("audit record failed: %s", exc)


def _valid_solarvolt_db(data: bytes) -> bool:
    """A restore upload is accepted only if it's a real SQLite file carrying our
    `schema_version` table — guards against restoring an arbitrary/foreign file."""
    if not data.startswith(b"SQLite format 3\x00"):
        return False
    import os
    import sqlite3
    import tempfile

    fd, tmp = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        conn = sqlite3.connect(tmp)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False
    finally:
        os.path.exists(tmp) and os.unlink(tmp)


def _validate_device_body(body: dict, *, require_id: bool) -> None:
    if require_id and not body.get("id"):
        raise HTTPException(status_code=422, detail="device 'id' is required")
    transport = body.get("transport", "dummy")
    if transport not in ("dummy", "modbus_rtu"):
        raise HTTPException(status_code=422, detail=f"unknown transport {transport!r}")
    if transport == "modbus_rtu":
        if not body.get("profile"):
            raise HTTPException(status_code=422, detail="modbus_rtu device needs a 'profile'")
        if not (body.get("params") or {}).get("port"):
            raise HTTPException(status_code=422, detail="modbus_rtu device needs params.port")


async def _add_to_registry(registry: DeviceRegistry, row: dict, clock) -> None:
    device = build_device_from_config(row, clock=clock)
    if device is None:
        return
    try:
        await device.connect()
    except TransportError:
        pass  # offline now -> reads will surface as stale (plan.md §10), don't block CRUD
    registry.add(device)


async def _remove_from_registry(registry: DeviceRegistry, device_id: str) -> None:
    device = registry.get(device_id)
    if device is not None:
        await device.close()
        registry.remove(device_id)


app = create_app()

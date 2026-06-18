"""FastAPI application (plan.md §7 API surface, §13 deployment).

Surface: health, live (REST + WebSocket), **history** (Phase 2), and **device config CRUD**
(Phase 2) — all driven by the dummy inverter so the whole stack is usable with no hardware.
The poller feeds a persistence service that writes samples, rolls them up, and prunes; the
History API reads those rollups. The built Angular frontend is served by this same app in
production (one process, one port); in dev the Angular dev server proxies here.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .devices.base import TransportError, system_clock
from .devices.factory import (
    build_device_from_config,
    build_registry_from_configs,
    default_device_configs,
)
from .devices.firmware import verify_firmware
from .devices.registry import DeviceRegistry
from .forecast.openmeteo import OpenMeteoClient
from .forecast.service import ForecastService
from .persistence import PersistenceService
from .poller import Poller
from .stats import StatsService
from .storage.repository import (
    AppConfigRepository,
    DeviceConfigRepository,
    SqliteHistoryRepository,
    open_repositories,
)
from .tariff import Tariff
from .version import __version__

# Where the built Angular app lands (Phase 0 frontend build output). Optional in dev.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "solar-manager" / "browser"


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

    history_repo, config_repo, app_config = await open_repositories(settings.db_path)
    app.state.history_repo = history_repo
    app.state.config_repo = config_repo
    app.state.app_config = app_config
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
    try:
        yield
    finally:
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
    app = FastAPI(title="Solar Manager", version=__version__, lifespan=lifespan)
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
                **poller.health(),
            }
        )

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
            "control": app.state.settings.enable_control and bool(device and "control" in device.capabilities()),
        }

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
    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")

    return app


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

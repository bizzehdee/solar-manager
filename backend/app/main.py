"""FastAPI application (plan.md §7 API surface, §13 deployment).

Phase 0 surface: /api/health, /api/live, and the /ws/live WebSocket — all driven by
the dummy inverter so the whole stack is usable with no hardware. The built Angular
frontend is served by this same app in production (one process, one port); in dev the
Angular dev server runs separately and proxies here.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .devices.base import Device, system_clock
from .devices.dummy import DummyProfile, NullTransport
from .devices.registry import DeviceRegistry
from .poller import Poller
from .version import __version__

# Where the built Angular app lands (Phase 0 frontend build output). Optional in dev.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "solar-manager" / "browser"


def build_default_registry(clock=system_clock) -> DeviceRegistry:
    """A fresh install has one device: the dummy inverter (plan.md §4)."""
    registry = DeviceRegistry()
    registry.add(
        Device("dummy", NullTransport(), DummyProfile(clock=clock), clock=clock)
    )
    return registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    registry: DeviceRegistry = app.state.registry
    await registry.connect_all()
    poller = Poller(registry, interval_s=settings.poll_interval_s)
    app.state.poller = poller
    await poller.start()
    try:
        yield
    finally:
        await poller.stop()
        await registry.close_all()


def create_app(settings: Settings | None = None, registry: DeviceRegistry | None = None) -> FastAPI:
    app = FastAPI(title="Solar Manager", version=__version__, lifespan=lifespan)
    app.state.settings = settings or Settings.from_env()
    app.state.registry = registry or build_default_registry()

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
            await ws.send_json(poller.snapshot())  # immediate current state
            while True:
                snap = await queue.get()
                await ws.send_json(snap)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            poller.unsubscribe(queue)

    # Serve the built frontend if present (production / packaged run). Harmless in dev.
    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")

    return app


app = create_app()

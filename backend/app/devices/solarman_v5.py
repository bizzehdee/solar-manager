"""SolarmanV5 transport (plan.md §4, §20; task L01).

A `pysolarmanv5` async client behind the `Transport` seam: it moves register values over
**TCP to a Solarman/IGEN data-logging stick** (the WiFi/LAN dongle, default port 8899) instead of
a direct RS485 cable. SolarmanV5 wraps the *identical* Modbus payload, so this transport reuses the
exact same profiles (`deye-base`, `sunsynk-…`) unchanged — only the wire differs.

Mirrors `modbus_rtu.py`: configurable host/serial/slave-id, bounded retries with exponential
backoff so a flaky link degrades to a stale device (plan.md §10) rather than crashing the poller,
and an injectable client factory so the whole retry/error surface is unit-testable against a fake
client with **no hardware** (the dummy-first convention applied to the transport layer).
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, Sequence

from .base import TransportError


@dataclass(frozen=True, slots=True)
class SolarmanV5Config:
    """Connection parameters for one logger. `serial` is the data-logger's own serial number
    (printed on the stick / in the Solarman app) — the SolarmanV5 frame is addressed to it."""

    host: str
    serial: int
    port: int = 8899
    slave_id: int = 1
    timeout_s: float = 5.0
    # Retry policy for a single read/write transaction.
    retries: int = 3
    backoff_s: float = 0.1       # base delay; doubles each retry
    backoff_max_s: float = 2.0   # cap on a single backoff sleep


class _SolarmanClient(Protocol):
    """The slice of pysolarmanv5's `PySolarmanV5Async` this transport relies on. Declared locally
    so tests can substitute a fake without importing pysolarmanv5 and without hardware."""

    async def connect(self) -> None: ...
    async def read_holding_registers(self, register_addr: int, quantity: int) -> list[int]: ...
    async def read_input_registers(self, register_addr: int, quantity: int) -> list[int]: ...
    async def write_multiple_holding_registers(self, register_addr: int, values: Sequence[int]): ...
    async def disconnect(self) -> None: ...


ClientFactory = Callable[[SolarmanV5Config], _SolarmanClient]


def _default_client_factory(config: SolarmanV5Config) -> _SolarmanClient:
    """Build a real pysolarmanv5 async client. Imported lazily so the dummy-only path (and most
    tests) never need pysolarmanv5 present at import time."""
    from pysolarmanv5 import PySolarmanV5Async

    return PySolarmanV5Async(
        config.host,
        config.serial,
        port=config.port,
        mb_slave_id=config.slave_id,
        socket_timeout=config.timeout_s,
        auto_reconnect=True,
    )


class SolarmanV5Source:
    """Async SolarmanV5 transport. Implements the `Transport` protocol (base.py)."""

    def __init__(
        self,
        config: SolarmanV5Config,
        *,
        client_factory: ClientFactory = _default_client_factory,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._sleep = sleep  # injectable so retry backoff is instant in tests
        self._client: _SolarmanClient | None = None
        # Comms stats surfaced on the Diagnostics page (T092).
        self._stats = {"transactions": 0, "failures": 0, "retries": 0,
                       "last_error": None, "last_rtt_ms": None}

    def comms_stats(self) -> dict:
        """Cumulative comms health (transactions / failures / retries, last error and round-trip
        time) for diagnostics."""
        return dict(self._stats)

    # --- Transport protocol -----------------------------------------------------
    async def connect(self) -> None:
        client = self._client_factory(self._config)
        try:
            await client.connect()
        except Exception as exc:  # socket/handshake errors
            raise TransportError(
                f"SolarmanV5 connect failed to {self._config.host}:{self._config.port} "
                f"(logger {self._config.serial}, slave {self._config.slave_id}): {exc}"
            ) from exc
        self._client = client

    async def read_registers(self, start: int, count: int, table: str = "holding") -> list[int]:
        if table == "holding":
            reader = lambda c: c.read_holding_registers(start, count)
        elif table == "input":
            reader = lambda c: c.read_input_registers(start, count)
        else:
            raise TransportError(f"Unknown register table: {table!r}")

        registers = await self._with_retries(reader, f"read {table}[{start}:{start + count}]")
        if registers is None or len(registers) != count:
            raise TransportError(
                f"Short read on {table}[{start}:{start + count}]: "
                f"expected {count} registers, got {registers!r}"
            )
        return list(registers)

    async def write_registers(self, start: int, values: Sequence[int]) -> None:
        values = list(values)
        await self._with_retries(
            lambda c: c.write_multiple_holding_registers(start, values),
            f"write[{start}:{start + len(values)}]",
        )

    async def close(self) -> None:
        if self._client is not None:
            result = self._client.disconnect()
            if inspect.isawaitable(result):
                await result
            self._client = None

    # --- retry/backoff ----------------------------------------------------------
    async def _with_retries(self, call: Callable[[_SolarmanClient], Awaitable], what: str):
        if self._client is None:
            raise TransportError(f"{what}: transport not connected")
        delay = self._config.backoff_s
        last_error: Exception | None = None
        self._stats["transactions"] += 1
        started = time.monotonic()
        for attempt in range(self._config.retries):
            try:
                result = await call(self._client)
            except Exception as exc:  # pysolarmanv5 raises on protocol/IO errors
                last_error = exc
            else:
                self._stats["last_rtt_ms"] = round((time.monotonic() - started) * 1000, 1)
                return result
            if attempt < self._config.retries - 1:
                self._stats["retries"] += 1
                await self._sleep(min(delay, self._config.backoff_max_s))
                delay *= 2
        self._stats["failures"] += 1
        self._stats["last_error"] = f"{what}: {last_error}"
        raise TransportError(f"{what}: failed after {self._config.retries} attempts") from last_error

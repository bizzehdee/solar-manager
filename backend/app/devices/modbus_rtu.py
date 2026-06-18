"""Modbus RTU transport (plan.md §4, task T030).

A `pymodbus` async serial client behind the `Transport` seam: it moves register
values over an RS485 adapter (`/dev/ttyUSB*`) and knows nothing about brands — what
the registers *mean* lives entirely in the profile. Configurable port/baud/slave-id,
with timeouts, bounded retries and exponential backoff so a flaky bus degrades to a
stale device (plan.md §10) instead of crashing the poller.

The underlying client is created through an injectable factory so the whole retry /
error / decode surface is unit-testable against a fake client with **no hardware** —
the dummy-first convention applied to the transport layer.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, Sequence

from .base import TransportError


@dataclass(frozen=True, slots=True)
class ModbusRtuConfig:
    """Serial-line + protocol parameters for one RTU device."""

    port: str
    baudrate: int = 9600
    slave_id: int = 1
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout_s: float = 1.0
    # Retry policy for a single read/write transaction.
    retries: int = 3
    backoff_s: float = 0.1       # base delay; doubles each retry
    backoff_max_s: float = 2.0   # cap on a single backoff sleep


class _ModbusClient(Protocol):
    """The slice of pymodbus's AsyncModbusSerialClient this transport relies on.

    Declared locally so tests can substitute a fake without importing pymodbus and
    without depending on hardware."""

    async def connect(self) -> bool: ...
    async def read_holding_registers(self, address: int, *, count: int, device_id: int): ...
    async def read_input_registers(self, address: int, *, count: int, device_id: int): ...
    async def write_registers(self, address: int, values, *, device_id: int): ...
    def close(self): ...


ClientFactory = Callable[[ModbusRtuConfig], _ModbusClient]


def _default_client_factory(config: ModbusRtuConfig) -> _ModbusClient:
    """Build a real pymodbus async serial client. Imported lazily so the dummy-only
    path (and most tests) never need pymodbus present at import time."""
    from pymodbus.client import AsyncModbusSerialClient

    return AsyncModbusSerialClient(
        port=config.port,
        baudrate=config.baudrate,
        bytesize=config.bytesize,
        parity=config.parity,
        stopbits=config.stopbits,
        timeout=config.timeout_s,
    )


class ModbusRtuSource:
    """Async Modbus-RTU transport. Implements the `Transport` protocol (base.py)."""

    def __init__(
        self,
        config: ModbusRtuConfig,
        *,
        client_factory: ClientFactory = _default_client_factory,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._sleep = sleep  # injectable so retry backoff is instant in tests
        self._client: _ModbusClient | None = None
        # Comms stats surfaced on the Diagnostics page (T092).
        self._stats = {"transactions": 0, "failures": 0, "retries": 0,
                       "last_error": None, "last_rtt_ms": None}

    def comms_stats(self) -> dict:
        """Cumulative Modbus comms health (transactions / failures / retries, last error
        and round-trip time) for diagnostics."""
        return dict(self._stats)

    # --- Transport protocol -----------------------------------------------------
    async def connect(self) -> None:
        client = self._client_factory(self._config)
        ok = await client.connect()
        if not ok:
            raise TransportError(
                f"Modbus RTU connect failed on {self._config.port} "
                f"@ {self._config.baudrate} baud (slave {self._config.slave_id})"
            )
        self._client = client

    async def read_registers(self, start: int, count: int, table: str = "holding") -> list[int]:
        if table == "holding":
            reader = lambda c: c.read_holding_registers(start, count=count, device_id=self._config.slave_id)
        elif table == "input":
            reader = lambda c: c.read_input_registers(start, count=count, device_id=self._config.slave_id)
        else:
            raise TransportError(f"Unknown register table: {table!r}")

        rsp = await self._with_retries(reader, f"read {table}[{start}:{start + count}]")
        registers = getattr(rsp, "registers", None)
        if registers is None or len(registers) != count:
            raise TransportError(
                f"Short read on {table}[{start}:{start + count}]: "
                f"expected {count} registers, got {registers!r}"
            )
        return list(registers)

    async def write_registers(self, start: int, values: Sequence[int]) -> None:
        values = list(values)
        await self._with_retries(
            lambda c: c.write_registers(start, values, device_id=self._config.slave_id),
            f"write[{start}:{start + len(values)}]",
        )

    async def close(self) -> None:
        if self._client is not None:
            result = self._client.close()
            if inspect.isawaitable(result):
                await result
            self._client = None

    # --- retry/backoff ----------------------------------------------------------
    async def _with_retries(self, call: Callable[[_ModbusClient], Awaitable], what: str):
        if self._client is None:
            raise TransportError(f"{what}: transport not connected")
        delay = self._config.backoff_s
        last_error: Exception | None = None
        self._stats["transactions"] += 1
        started = time.monotonic()
        for attempt in range(self._config.retries):
            try:
                rsp = await call(self._client)
            except Exception as exc:  # pymodbus raises a variety of connection/IO errors
                last_error = exc
            else:
                # pymodbus signals protocol-level errors via isError() rather than raising.
                if hasattr(rsp, "isError") and rsp.isError():
                    last_error = TransportError(f"{what}: device returned error {rsp!r}")
                else:
                    self._stats["last_rtt_ms"] = round((time.monotonic() - started) * 1000, 1)
                    return rsp
            if attempt < self._config.retries - 1:
                self._stats["retries"] += 1
                await self._sleep(min(delay, self._config.backoff_max_s))
                delay *= 2
        self._stats["failures"] += 1
        self._stats["last_error"] = f"{what}: {last_error}"
        raise TransportError(f"{what}: failed after {self._config.retries} attempts") from last_error

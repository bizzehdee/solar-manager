"""Modbus TCP transport (plan.md §4, §20; task L19).

A `pymodbus` async TCP client behind the `Transport` seam: it moves register values over
**Modbus/TCP (the standard port-502 protocol)** to an inverter or gateway on the LAN, instead of a
direct RS485 cable (`modbus_rtu`) or a Solarman logger (`solarman_v5`). The framing differs but the
payload is identical Modbus, so this transport reuses the *exact same* profiles (`deye-base`,
`sunsynk-…`) unchanged — only the wire differs.

Mirrors `modbus_rtu.py`/`solarman_v5.py`: host/port/slave-id, bounded retries with exponential
backoff so a flaky link degrades to a stale device (plan.md §10) rather than crashing the poller,
and an injectable client factory so the whole retry/error surface is unit-testable against a fake
client with **no hardware**.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, Sequence

from .base import TransportError


@dataclass(frozen=True, slots=True)
class ModbusTcpConfig:
    """Connection parameters for one Modbus/TCP device."""

    host: str
    port: int = 502
    slave_id: int = 1
    timeout_s: float = 3.0
    # Retry policy for a single read/write transaction.
    retries: int = 3
    backoff_s: float = 0.1       # base delay; doubles each retry
    backoff_max_s: float = 2.0   # cap on a single backoff sleep


class _ModbusClient(Protocol):
    """The slice of pymodbus's AsyncModbusTcpClient this transport relies on. Declared locally so
    tests can substitute a fake without importing pymodbus and without hardware."""

    async def connect(self) -> bool: ...
    async def read_holding_registers(self, address: int, *, count: int, device_id: int): ...
    async def read_input_registers(self, address: int, *, count: int, device_id: int): ...
    async def write_registers(self, address: int, values, *, device_id: int): ...
    def close(self): ...


ClientFactory = Callable[[ModbusTcpConfig], _ModbusClient]


def _default_client_factory(config: ModbusTcpConfig) -> _ModbusClient:
    """Build a real pymodbus async TCP client. Imported lazily so the dummy-only path (and most
    tests) never need pymodbus present at import time."""
    from pymodbus.client import AsyncModbusTcpClient

    return AsyncModbusTcpClient(config.host, port=config.port, timeout=config.timeout_s)


class ModbusTcpSource:
    """Async Modbus/TCP transport. Implements the `Transport` protocol (base.py)."""

    def __init__(
        self,
        config: ModbusTcpConfig,
        *,
        client_factory: ClientFactory = _default_client_factory,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._sleep = sleep  # injectable so retry backoff is instant in tests
        self._client: _ModbusClient | None = None
        self._stats = {"transactions": 0, "failures": 0, "retries": 0,
                       "last_error": None, "last_rtt_ms": None}

    def comms_stats(self) -> dict:
        """Cumulative comms health (transactions / failures / retries, last error and round-trip
        time) for the Diagnostics page (T092)."""
        return dict(self._stats)

    # --- Transport protocol -----------------------------------------------------
    async def connect(self) -> None:
        client = self._client_factory(self._config)
        try:
            ok = await client.connect()
        except Exception as exc:  # socket/handshake errors
            raise TransportError(
                f"Modbus/TCP connect failed to {self._config.host}:{self._config.port}: {exc}"
            ) from exc
        if ok is False:
            raise TransportError(
                f"Modbus/TCP connect failed to {self._config.host}:{self._config.port}"
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

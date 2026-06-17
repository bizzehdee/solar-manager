"""Modbus RTU transport (plan.md §4, §10; task T030).

Exercised against a fake pymodbus client — no hardware, no serial port. Covers the
gnarly bits: dispatch by register table, short-read detection, the retry/backoff loop,
pymodbus's two failure modes (raised exception vs `isError()`), and connect/close.
"""

from __future__ import annotations

import pytest

from app.devices.base import TransportError
from app.devices.modbus_rtu import ModbusRtuConfig, ModbusRtuSource


class FakeResponse:
    def __init__(self, registers=None, *, error=False):
        self.registers = registers
        self._error = error

    def isError(self) -> bool:
        return self._error


class FakeClient:
    """Scripted client. `script` is a list of actions consumed per read/write call:
    ('ok', [regs]) -> success, ('err',) -> isError() response, ('raise', exc) -> raise."""

    def __init__(self, *, connect_ok=True, script=None):
        self._connect_ok = connect_ok
        self._script = list(script or [])
        self.calls: list[tuple] = []
        self.closed = False

    async def connect(self) -> bool:
        return self._connect_ok

    async def _consume(self, kind, address, count, device_id):
        self.calls.append((kind, address, count, device_id))
        action = self._script.pop(0)
        if action[0] == "raise":
            raise action[1]
        if action[0] == "err":
            return FakeResponse(error=True)
        return FakeResponse(registers=action[1])

    async def read_holding_registers(self, address, *, count, device_id):
        return await self._consume("holding", address, count, device_id)

    async def read_input_registers(self, address, *, count, device_id):
        return await self._consume("input", address, count, device_id)

    async def write_registers(self, address, values, *, device_id):
        self.calls.append(("write", address, tuple(values), device_id))
        action = self._script.pop(0)
        if action[0] == "raise":
            raise action[1]
        if action[0] == "err":
            return FakeResponse(error=True)
        return FakeResponse(registers=list(values))

    def close(self):
        self.closed = True


def _source(client, **cfg):
    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    config = ModbusRtuConfig(port="/dev/null", slave_id=cfg.pop("slave_id", 7), **cfg)
    src = ModbusRtuSource(config, client_factory=lambda c: client, sleep=fake_sleep)
    return src, sleeps


async def test_connect_success_stores_client():
    client = FakeClient()
    src, _ = _source(client)
    await src.connect()
    assert src._client is client


async def test_connect_failure_raises():
    src, _ = _source(FakeClient(connect_ok=False))
    with pytest.raises(TransportError, match="connect failed"):
        await src.connect()


async def test_read_holding_dispatch_and_slave_id():
    client = FakeClient(script=[("ok", [10, 20, 30])])
    src, _ = _source(client, slave_id=7)
    await src.connect()
    assert await src.read_registers(100, 3, "holding") == [10, 20, 30]
    assert client.calls == [("holding", 100, 3, 7)]


async def test_read_input_table_dispatch():
    client = FakeClient(script=[("ok", [1, 2])])
    src, _ = _source(client)
    await src.connect()
    assert await src.read_registers(5, 2, "input") == [1, 2]
    assert client.calls[0][0] == "input"


async def test_unknown_table_raises():
    client = FakeClient()
    src, _ = _source(client)
    await src.connect()
    with pytest.raises(TransportError, match="Unknown register table"):
        await src.read_registers(0, 1, "coil")


async def test_short_read_is_an_error():
    client = FakeClient(script=[("ok", [1, 2])])  # asked for 3, got 2
    src, _ = _source(client)
    await src.connect()
    with pytest.raises(TransportError, match="Short read"):
        await src.read_registers(0, 3, "holding")


async def test_read_before_connect_raises():
    client = FakeClient(script=[("ok", [1])])
    src, _ = _source(client)
    with pytest.raises(TransportError, match="not connected"):
        await src.read_registers(0, 1)


async def test_retry_then_success_with_exponential_backoff():
    client = FakeClient(script=[("raise", OSError("bus")), ("err",), ("ok", [42])])
    src, sleeps = _source(client, retries=3, backoff_s=0.1)
    await src.connect()
    assert await src.read_registers(0, 1) == [42]
    assert len(client.calls) == 3
    assert sleeps == [0.1, 0.2]  # one sleep before each retry, doubling


async def test_retries_exhausted_raises_with_cause():
    client = FakeClient(script=[("raise", OSError("x")), ("raise", OSError("y")), ("raise", OSError("z"))])
    src, sleeps = _source(client, retries=3, backoff_s=0.1)
    await src.connect()
    with pytest.raises(TransportError, match="failed after 3 attempts") as ei:
        await src.read_registers(0, 1)
    assert isinstance(ei.value.__cause__, OSError)
    assert sleeps == [0.1, 0.2]


async def test_backoff_is_capped():
    script = [("raise", OSError("e"))] * 4
    client = FakeClient(script=script)
    src, sleeps = _source(client, retries=4, backoff_s=1.0, backoff_max_s=1.5)
    await src.connect()
    with pytest.raises(TransportError):
        await src.read_registers(0, 1)
    assert sleeps == [1.0, 1.5, 1.5]  # 1.0, then 2.0->cap 1.5, then 4.0->cap 1.5


async def test_iserror_response_retried():
    client = FakeClient(script=[("err",), ("ok", [9])])
    src, _ = _source(client, retries=2, backoff_s=0.01)
    await src.connect()
    assert await src.read_registers(0, 1) == [9]


async def test_write_registers_passes_values_and_slave():
    client = FakeClient(script=[("ok", None)])
    src, _ = _source(client, slave_id=3)
    await src.connect()
    await src.write_registers(250, [1300, 0])
    assert client.calls == [("write", 250, (1300, 0), 3)]


async def test_write_failure_raises():
    client = FakeClient(script=[("err",)])
    src, _ = _source(client, retries=1)
    await src.connect()
    with pytest.raises(TransportError):
        await src.write_registers(250, [1])


async def test_close_is_idempotent_and_closes_client():
    client = FakeClient()
    src, _ = _source(client)
    await src.connect()
    await src.close()
    assert client.closed is True
    await src.close()  # no client now; must not raise


async def test_close_awaits_async_close():
    closed = []

    class AsyncCloseClient(FakeClient):
        async def close(self):  # some pymodbus versions/clients are async
            closed.append(True)

    client = AsyncCloseClient()
    src, _ = _source(client)
    await src.connect()
    await src.close()
    assert closed == [True]


async def test_default_client_factory_builds_pymodbus_client():
    # Constructs a real AsyncModbusSerialClient (no connect attempted) — proves the
    # production wiring matches the installed pymodbus API. Async because the client
    # binds the running event loop at construction.
    from app.devices.modbus_rtu import _default_client_factory

    client = _default_client_factory(ModbusRtuConfig(port="/dev/ttyUSB-test", baudrate=19200))
    assert hasattr(client, "read_holding_registers")
    assert hasattr(client, "connect")

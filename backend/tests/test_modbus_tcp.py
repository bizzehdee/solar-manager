"""Modbus TCP transport (plan.md §4, §10, §20; task L19).

Exercised against a fake pymodbus async TCP client — no hardware. Covers dispatch by register
table, short-read detection, isError() handling, the retry/backoff loop, and connect/close.
"""

from __future__ import annotations

import pytest

from app.devices.base import TransportError
from app.devices.modbus_tcp import ModbusTcpConfig, ModbusTcpSource


class _Rsp:
    def __init__(self, registers=None, error=False):
        self.registers = registers
        self._error = error

    def isError(self):
        return self._error


class FakeClient:
    """Scripted pymodbus-style client. `script` items consumed per read/write:
    ('ok', [regs]) → response; ('err',) → isError() response; ('raise', exc) → raise."""

    def __init__(self, *, connect_result=True, connect_exc=None, script=None):
        self._connect_result = connect_result
        self._connect_exc = connect_exc
        self._script = list(script or [])
        self.calls: list[tuple] = []
        self.closed = False

    async def connect(self):
        if self._connect_exc is not None:
            raise self._connect_exc
        return self._connect_result

    def _next(self):
        action = self._script.pop(0)
        if action[0] == "raise":
            raise action[1]
        if action[0] == "err":
            return _Rsp(error=True)
        return _Rsp(registers=list(action[1]))

    async def read_holding_registers(self, address, *, count, device_id):
        self.calls.append(("holding", address, count, device_id))
        return self._next()

    async def read_input_registers(self, address, *, count, device_id):
        self.calls.append(("input", address, count, device_id))
        return self._next()

    async def write_registers(self, address, values, *, device_id):
        self.calls.append(("write", address, tuple(values), device_id))
        return self._next()

    def close(self):
        self.closed = True


def _source(client, **cfg):
    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    config = ModbusTcpConfig(host=cfg.pop("host", "10.0.0.9"), slave_id=cfg.pop("slave_id", 3), **cfg)
    src = ModbusTcpSource(config, client_factory=lambda c: client, sleep=fake_sleep)
    return src, sleeps


@pytest.mark.asyncio
async def test_reads_holding_and_input_tables_with_slave_id():
    client = FakeClient(script=[("ok", [1, 2, 3]), ("ok", [9])])
    src, _ = _source(client)
    await src.connect()
    assert await src.read_registers(100, 3, "holding") == [1, 2, 3]
    assert await src.read_registers(200, 1, "input") == [9]
    assert client.calls == [("holding", 100, 3, 3), ("input", 200, 1, 3)]


@pytest.mark.asyncio
async def test_unknown_table_raises():
    src, _ = _source(FakeClient(script=[]))
    await src.connect()
    with pytest.raises(TransportError):
        await src.read_registers(0, 1, "coils")


@pytest.mark.asyncio
async def test_short_read_is_an_error():
    client = FakeClient(script=[("ok", [1, 2])])  # asked for 3, got 2
    src, _ = _source(client)
    await src.connect()
    with pytest.raises(TransportError):
        await src.read_registers(0, 3)


@pytest.mark.asyncio
async def test_connect_failure_raises_transport_error():
    src, _ = _source(FakeClient(connect_result=False))
    with pytest.raises(TransportError):
        await src.connect()


@pytest.mark.asyncio
async def test_retries_then_succeeds_and_counts_stats():
    client = FakeClient(script=[("raise", OSError("boom")), ("err",), ("ok", [5, 6])])
    src, sleeps = _source(client, retries=3)
    await src.connect()
    assert await src.read_registers(10, 2) == [5, 6]
    stats = src.comms_stats()
    assert stats["transactions"] == 1 and stats["retries"] == 2 and stats["failures"] == 0
    assert len(sleeps) == 2  # backoff between the 3 attempts


@pytest.mark.asyncio
async def test_gives_up_after_retries_and_records_failure():
    client = FakeClient(script=[("raise", OSError("x"))] * 3)
    src, _ = _source(client, retries=3)
    await src.connect()
    with pytest.raises(TransportError):
        await src.read_registers(0, 1)
    assert src.comms_stats()["failures"] == 1


@pytest.mark.asyncio
async def test_write_dispatches_and_close_is_clean():
    client = FakeClient(script=[("ok", [])])
    src, _ = _source(client)
    await src.connect()
    await src.write_registers(50, [7, 8])
    assert client.calls[-1] == ("write", 50, (7, 8), 3)
    await src.close()
    assert client.closed is True

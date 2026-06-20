"""SolarmanV5 transport (plan.md §4, §10, §20; task L01).

Exercised against a fake pysolarmanv5 client — no hardware, no logger. Covers dispatch by
register table, short-read detection, the retry/backoff loop, connect/close, and that the real
client factory matches the installed pysolarmanv5 API. SolarmanV5 signals errors by raising
(no isError() response), so the failure modes are exceptions only.
"""

from __future__ import annotations

import pytest

from app.devices.base import TransportError
from app.devices.solarman_v5 import SolarmanV5Config, SolarmanV5Source


class FakeClient:
    """Scripted client. `script` actions consumed per read/write: ('ok', [regs]) -> success,
    ('raise', exc) -> raise."""

    def __init__(self, *, connect_exc=None, script=None):
        self._connect_exc = connect_exc
        self._script = list(script or [])
        self.calls: list[tuple] = []
        self.closed = False

    async def connect(self) -> None:
        if self._connect_exc is not None:
            raise self._connect_exc

    async def _consume(self, kind, address, quantity):
        self.calls.append((kind, address, quantity))
        action = self._script.pop(0)
        if action[0] == "raise":
            raise action[1]
        return list(action[1])

    async def read_holding_registers(self, register_addr, quantity):
        return await self._consume("holding", register_addr, quantity)

    async def read_input_registers(self, register_addr, quantity):
        return await self._consume("input", register_addr, quantity)

    async def write_multiple_holding_registers(self, register_addr, values):
        self.calls.append(("write", register_addr, tuple(values)))
        action = self._script.pop(0)
        if action[0] == "raise":
            raise action[1]
        return len(values)

    async def disconnect(self) -> None:
        self.closed = True


def _source(client, **cfg):
    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    config = SolarmanV5Config(
        host=cfg.pop("host", "10.0.0.5"),
        serial=cfg.pop("serial", 1234567890),
        slave_id=cfg.pop("slave_id", 7),
        **cfg,
    )
    src = SolarmanV5Source(config, client_factory=lambda c: client, sleep=fake_sleep)
    return src, sleeps


async def test_connect_success_stores_client():
    client = FakeClient()
    src, _ = _source(client)
    await src.connect()
    assert src._client is client


async def test_connect_failure_raises():
    src, _ = _source(FakeClient(connect_exc=OSError("no route")))
    with pytest.raises(TransportError, match="connect failed"):
        await src.connect()


async def test_read_holding_dispatch():
    client = FakeClient(script=[("ok", [10, 20, 30])])
    src, _ = _source(client)
    await src.connect()
    assert await src.read_registers(100, 3, "holding") == [10, 20, 30]
    assert client.calls == [("holding", 100, 3)]


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
    client = FakeClient(script=[("raise", OSError("blip")), ("raise", OSError("blip")), ("ok", [42])])
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
    client = FakeClient(script=[("raise", OSError("e"))] * 4)
    src, sleeps = _source(client, retries=4, backoff_s=1.0, backoff_max_s=1.5)
    await src.connect()
    with pytest.raises(TransportError):
        await src.read_registers(0, 1)
    assert sleeps == [1.0, 1.5, 1.5]


async def test_write_registers_passes_values():
    client = FakeClient(script=[("ok", [])])
    src, _ = _source(client)
    await src.connect()
    await src.write_registers(250, [1300, 0])
    assert client.calls == [("write", 250, (1300, 0))]


async def test_write_failure_raises():
    client = FakeClient(script=[("raise", OSError("nak"))])
    src, _ = _source(client, retries=1)
    await src.connect()
    with pytest.raises(TransportError):
        await src.write_registers(250, [1])


async def test_close_is_idempotent_and_disconnects_client():
    client = FakeClient()
    src, _ = _source(client)
    await src.connect()
    await src.close()
    assert client.closed is True
    await src.close()  # no client now; must not raise


async def test_comms_stats_track_transactions_and_failures():
    client = FakeClient(script=[("ok", [1]), ("raise", OSError("x"))])
    src, _ = _source(client, retries=1)
    await src.connect()
    await src.read_registers(0, 1)
    with pytest.raises(TransportError):
        await src.read_registers(0, 1)
    stats = src.comms_stats()
    assert stats["transactions"] == 2 and stats["failures"] == 1


async def test_default_client_factory_builds_pysolarmanv5_client():
    pytest.importorskip("pysolarmanv5")
    from app.devices.solarman_v5 import _default_client_factory

    client = _default_client_factory(SolarmanV5Config(host="10.0.0.9", serial=999, port=8899))
    assert hasattr(client, "read_holding_registers")
    assert hasattr(client, "connect")

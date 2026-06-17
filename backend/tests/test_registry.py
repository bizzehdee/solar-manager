"""Device registry + poller (plan.md §4/§5, §10, §21)."""

from __future__ import annotations

from app.devices.base import Device, system_clock
from app.devices.dummy import DummyProfile, NullTransport
from app.devices.registry import DeviceRegistry
from app.models import Reading
from app.poller import Poller


def _dummy_device(device_id="dummy", clock=system_clock) -> Device:
    return Device(device_id, NullTransport(), DummyProfile(clock=clock), clock=clock)


async def test_read_all_returns_one_reading_per_device(fixed_clock):
    reg = DeviceRegistry()
    reg.add(_dummy_device("a", fixed_clock))
    reg.add(_dummy_device("b", fixed_clock))
    readings = await reg.read_all()
    assert {r.device_id for r in readings} == {"a", "b"}
    assert all(isinstance(r, Reading) and r.metrics for r in readings)


async def test_failing_device_is_skipped_not_raised(fixed_clock):
    class Boom(DummyProfile):
        def decode(self, raw):  # noqa: ANN001
            raise RuntimeError("transport down")

    reg = DeviceRegistry()
    reg.add(_dummy_device("ok", fixed_clock))
    reg.add(Device("bad", NullTransport(), Boom(clock=fixed_clock), clock=fixed_clock))
    readings = await reg.read_all()
    assert {r.device_id for r in readings} == {"ok"}  # bad one skipped, no exception


async def test_poller_snapshot_and_health(fixed_clock):
    reg = DeviceRegistry()
    reg.add(_dummy_device("dummy", fixed_clock))
    poller = Poller(reg, interval_s=60)
    await poller.ensure_polled()
    snap = poller.snapshot()
    assert "dummy" in snap["devices"]
    assert snap["devices"]["dummy"]["metrics"]["pv_power_w"] > 0
    health = poller.health()
    assert health["devices"][0]["online"] is True


async def test_subscriber_receives_broadcast(fixed_clock):
    reg = DeviceRegistry()
    reg.add(_dummy_device("dummy", fixed_clock))
    poller = Poller(reg, interval_s=60)
    q = poller.subscribe()
    await poller.poll_once()
    snap = q.get_nowait()
    assert "dummy" in snap["devices"]

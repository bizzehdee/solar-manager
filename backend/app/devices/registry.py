"""Device registry — N devices, each = Transport x Profile (plan.md §4/§5).

Holds every configured device, reads them concurrently, and merges their readings
into one normalized snapshot keyed by `device_id`. A direct-connected BMS is just
another device row; mixed-brand systems fall out of this for free.
"""

from __future__ import annotations

import asyncio

from ..models import Reading
from .base import Device


class DeviceRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}

    def add(self, device: Device) -> None:
        self._devices[device.device_id] = device

    def remove(self, device_id: str) -> None:
        self._devices.pop(device_id, None)

    def get(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    @property
    def devices(self) -> list[Device]:
        return list(self._devices.values())

    async def connect_all(self) -> None:
        await asyncio.gather(*(d.connect() for d in self._devices.values()))

    async def close_all(self) -> None:
        await asyncio.gather(
            *(d.close() for d in self._devices.values()), return_exceptions=True
        )

    async def read_all(self) -> list[Reading]:
        """Read every device concurrently. A device that errors is skipped (its data
        goes stale honestly, plan.md §10) rather than failing the whole snapshot."""
        results = await asyncio.gather(
            *(d.read() for d in self._devices.values()), return_exceptions=True
        )
        readings: list[Reading] = []
        for device, result in zip(self._devices.values(), results):
            if isinstance(result, Reading):
                readings.append(result)
            # else: transport/decode error — surfaced via health() as stale, not raised.
        return readings

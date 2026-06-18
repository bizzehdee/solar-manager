"""The two orthogonal seams that keep the app vendor- and wire-agnostic (plan.md §4).

- Transport = *how* registers move (Modbus RTU/TCP, SolarmanV5...). No brand knowledge.
- DeviceProfile = *what* registers mean for a brand/model. No wire knowledge.
- Device = one transport + one profile; the rest of the app consumes a `Reading`.

The register-shaped Transport/Profile methods below are the **Modbus-family form**. The
cross-family contract the app depends on is just `Reading` (+ optional settings, Phase 5) —
so the text/Victron families (§20) can be added without touching anything above the driver.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable

from ..models import DeviceInfo, MetricValue, Reading

# A clock returns "now". Injected so the dummy + tests are deterministic (plan.md §21).
Clock = Callable[[], datetime]


def system_clock() -> datetime:
    """Timezone-aware local now (local hour matters for time-of-day synthesis)."""
    return datetime.now().astimezone()


class TransportError(Exception):
    """A transport failed to move bytes (connect/read/write). Raised by transports so
    the registry can degrade that device to stale (plan.md §10) rather than crash."""


@dataclass(frozen=True, slots=True)
class RegBlock:
    """A contiguous run of registers to read in one transaction."""

    start: int
    count: int
    table: str = "holding"  # "holding" | "input"


@runtime_checkable
class Transport(Protocol):
    """How bytes move. Knows nothing about brands."""

    async def connect(self) -> None: ...
    async def read_registers(self, start: int, count: int, table: str = "holding") -> list[int]: ...
    async def write_registers(self, start: int, values: Sequence[int]) -> None: ...  # control (Phase 6)
    async def close(self) -> None: ...


@runtime_checkable
class DeviceProfile(Protocol):
    """What the registers mean. Knows nothing about the wire."""

    vendor: str

    def register_blocks(self) -> list[RegBlock]: ...
    def decode(self, raw: Mapping[int, int]) -> dict[str, MetricValue]: ...
    def capabilities(self) -> set[str]: ...

    @property
    def info(self) -> DeviceInfo: ...


class Device:
    """Composition the rest of the app consumes: one transport + one profile.

    A profile that synthesizes its own readings (e.g. the dummy) returns no register
    blocks; its `decode` ignores the (empty) raw map. Register-backed profiles read
    their blocks through the transport, then decode.
    """

    def __init__(
        self,
        device_id: str,
        transport: Transport,
        profile: DeviceProfile,
        *,
        clock: Clock = system_clock,
    ) -> None:
        self.device_id = device_id
        self.transport = transport
        self.profile = profile
        self._clock = clock

    async def connect(self) -> None:
        await self.transport.connect()

    async def close(self) -> None:
        await self.transport.close()

    async def read(self) -> Reading:
        ts = self._clock()
        raw = await self._gather_raw()
        metrics = self.profile.decode(raw)
        return Reading(ts=ts, device_id=self.device_id, metrics=metrics)

    async def _gather_raw(self) -> dict[int, int]:
        raw: dict[int, int] = {}
        for block in self.profile.register_blocks():
            regs = await self.transport.read_registers(block.start, block.count, block.table)
            for offset, value in enumerate(regs):
                raw[block.start + offset] = value
        return raw

    def capabilities(self) -> set[str]:
        return self.profile.capabilities()

    @property
    def info(self) -> DeviceInfo:
        return self.profile.info

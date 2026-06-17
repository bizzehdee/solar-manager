"""Shared data types that cross the device seam (plan.md §4).

The cross-family contract is a `Reading` (canonical metrics) + optional settings —
NOT registers. Keep Modbus specifics inside the Modbus family.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# A decoded metric value. Most are numeric; status/fault keys may carry a decoded
# string or a list of human-readable codes (plan.md §4/§16).
MetricValue = float | int | str | list[str]


@dataclass(slots=True)
class Reading:
    ts: datetime
    device_id: str
    metrics: dict[str, MetricValue] = field(default_factory=dict)


@dataclass(slots=True)
class DeviceInfo:
    vendor: str
    model: str = ""
    serial: str | None = None
    firmware: dict[str, str] | None = None
    ratings: dict[str, float] | None = None

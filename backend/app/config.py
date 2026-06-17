"""Runtime configuration, sourced from environment variables.

One config surface used by every deployment path (plan.md §13). Kept dependency-light
on purpose — just the standard library reading the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    # Master switch for write-back / control (plan.md §12). OFF by default — the app
    # is monitoring-only out of the box. A *deployment* decision, not a UI toggle.
    enable_control: bool = False
    # How often the poller reads every device, in seconds (plan.md §10).
    poll_interval_s: float = 3.0
    # SQLite file location (Phase 2 uses it; defined here so the surface is stable).
    db_path: str = "solar-manager.db"

    # Real-hardware device (Phase 1). When `modbus_port` is set, the default registry
    # serves this real inverter over RTU instead of the dummy. Unset ⇒ dummy default,
    # so a fresh clone still runs with zero hardware (plan.md §13). The full per-device
    # config DB arrives in Phase 2 (T047); this env path bridges until then.
    modbus_port: str | None = None
    modbus_baudrate: int = 9600
    modbus_slave_id: int = 1
    modbus_profile: str = "sunsynk-8k-sg05lp1"
    modbus_device_id: str = "sunsynk"

    @classmethod
    def from_env(cls) -> "Settings":
        port = os.environ.get("SOLAR_MANAGER_MODBUS_PORT") or None
        return cls(
            enable_control=_env_bool("SOLAR_MANAGER_ENABLE_CONTROL", False),
            poll_interval_s=float(os.environ.get("SOLAR_MANAGER_POLL_INTERVAL_S", "3.0")),
            db_path=os.environ.get("SOLAR_MANAGER_DB_PATH", "solar-manager.db"),
            modbus_port=port,
            modbus_baudrate=int(os.environ.get("SOLAR_MANAGER_MODBUS_BAUD", "9600")),
            modbus_slave_id=int(os.environ.get("SOLAR_MANAGER_MODBUS_SLAVE_ID", "1")),
            modbus_profile=os.environ.get("SOLAR_MANAGER_MODBUS_PROFILE", "sunsynk-8k-sg05lp1"),
            modbus_device_id=os.environ.get("SOLAR_MANAGER_MODBUS_DEVICE_ID", "sunsynk"),
        )

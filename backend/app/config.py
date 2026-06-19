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
    # This is the ONE gate on touching inverter registers — both the settings write API and
    # rule-based automation's register writes (apply/scheduler) are guarded by it. Automation
    # itself (rules, preview, and any future webhook/notification actions) needs no flag.
    enable_control: bool = False
    # How often the poller reads every device, in seconds (plan.md §10).
    poll_interval_s: float = 3.0
    # SQLite file location (plan.md §5).
    db_path: str = "solarvolt.db"
    # Persistence cadence + retention (plan.md §5, §10) — decoupled from poll rate.
    persist_interval_s: float = 30.0
    aggregate_interval_s: float = 300.0
    history_retention_days: float = 14.0
    # How often the alert engine evaluates rules against the live snapshot (plan.md §15).
    alert_interval_s: float = 30.0
    # How often the automation scheduler re-evaluates rules and applies the armed winners
    # (plan.md §18; L03e-3). Only runs when control + automation are both enabled. Settings
    # changes aren't time-critical and each apply re-reads/writes the inverter, so this is slow.
    automation_interval_s: float = 300.0

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
        port = os.environ.get("SOLARVOLT_MODBUS_PORT") or None
        return cls(
            enable_control=_env_bool("SOLARVOLT_ENABLE_CONTROL", False),
            poll_interval_s=float(os.environ.get("SOLARVOLT_POLL_INTERVAL_S", "3.0")),
            db_path=os.environ.get("SOLARVOLT_DB_PATH", "solarvolt.db"),
            persist_interval_s=float(os.environ.get("SOLARVOLT_PERSIST_INTERVAL_S", "30.0")),
            aggregate_interval_s=float(os.environ.get("SOLARVOLT_AGGREGATE_INTERVAL_S", "300.0")),
            history_retention_days=float(os.environ.get("SOLARVOLT_RETENTION_DAYS", "14.0")),
            alert_interval_s=float(os.environ.get("SOLARVOLT_ALERT_INTERVAL_S", "30.0")),
            automation_interval_s=float(os.environ.get("SOLARVOLT_AUTOMATION_INTERVAL_S", "300.0")),
            modbus_port=port,
            modbus_baudrate=int(os.environ.get("SOLARVOLT_MODBUS_BAUD", "9600")),
            modbus_slave_id=int(os.environ.get("SOLARVOLT_MODBUS_SLAVE_ID", "1")),
            modbus_profile=os.environ.get("SOLARVOLT_MODBUS_PROFILE", "sunsynk-8k-sg05lp1"),
            modbus_device_id=os.environ.get("SOLARVOLT_MODBUS_DEVICE_ID", "sunsynk"),
        )

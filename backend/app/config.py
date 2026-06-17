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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            enable_control=_env_bool("SOLAR_MANAGER_ENABLE_CONTROL", False),
            poll_interval_s=float(os.environ.get("SOLAR_MANAGER_POLL_INTERVAL_S", "3.0")),
            db_path=os.environ.get("SOLAR_MANAGER_DB_PATH", "solar-manager.db"),
        )

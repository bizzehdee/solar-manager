"""Persistence layer (plan.md §5): a repository abstraction over SQLite + a rollup
schema, with versioned migrations run on boot. The rest of the app depends only on the
repository interface, never on SQL — so the storage engine stays swappable."""

from .db import connect
from .migrations import SCHEMA_VERSION, run_migrations
from .repository import (
    AlertRepository,
    AppConfigRepository,
    AuditRepository,
    DeviceConfigRepository,
    SeriesPoint,
    SqliteHistoryRepository,
    open_repositories,
)

__all__ = [
    "connect",
    "run_migrations",
    "SCHEMA_VERSION",
    "SqliteHistoryRepository",
    "DeviceConfigRepository",
    "AppConfigRepository",
    "AuditRepository",
    "AlertRepository",
    "SeriesPoint",
    "open_repositories",
]

"""Versioned schema migrations, run on boot (plan.md §5, §19; task T041).

**On Alembic:** task T041 names Alembic, but Alembic pulls in SQLAlchemy — a heavy
dependency that fights the project's repeatedly-stated leanness goal ("kept lean so the
native Pi install stays trivial", "low-footprint, SQLite, no heavy DB"). This module is a
deliberately lightweight equivalent that meets the same *done-criteria*: a **versioned
schema**, **migrations applied on startup**, and **additive-only** steps so upgrades never
lose history. Each migration is an (version, SQL) pair applied once, tracked in
`schema_version`. If a heavier migration story is ever needed, swapping this for Alembic is
contained to the storage package.
"""

from __future__ import annotations

import sqlite3

# Each entry: (version, idempotent-friendly DDL). Append new versions; never edit or
# reorder shipped ones (that would diverge installed DBs from fresh ones).
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        -- Raw instantaneous samples. ts is epoch seconds (REAL) so bucketing is arithmetic.
        CREATE TABLE samples (
            ts        REAL NOT NULL,
            device_id TEXT NOT NULL,
            metric    TEXT NOT NULL,
            value     REAL NOT NULL
        );
        CREATE INDEX ix_samples_lookup ON samples (device_id, metric, ts);
        CREATE INDEX ix_samples_ts ON samples (ts);

        -- Rollups: one row per (bucket, device, metric). avg/min/max for instantaneous
        -- metrics; last for cumulative counters. bucket is epoch seconds floored to width.
        CREATE TABLE rollup_5m (
            bucket REAL NOT NULL, device_id TEXT NOT NULL, metric TEXT NOT NULL,
            avg REAL NOT NULL, min REAL NOT NULL, max REAL NOT NULL, last REAL NOT NULL,
            n INTEGER NOT NULL,
            PRIMARY KEY (bucket, device_id, metric)
        );
        CREATE TABLE rollup_1h (
            bucket REAL NOT NULL, device_id TEXT NOT NULL, metric TEXT NOT NULL,
            avg REAL NOT NULL, min REAL NOT NULL, max REAL NOT NULL, last REAL NOT NULL,
            n INTEGER NOT NULL,
            PRIMARY KEY (bucket, device_id, metric)
        );
        CREATE TABLE rollup_1d (
            bucket REAL NOT NULL, device_id TEXT NOT NULL, metric TEXT NOT NULL,
            avg REAL NOT NULL, min REAL NOT NULL, max REAL NOT NULL, last REAL NOT NULL,
            n INTEGER NOT NULL,
            PRIMARY KEY (bucket, device_id, metric)
        );

        -- Small key/value store for watermarks etc.
        CREATE TABLE meta (key TEXT PRIMARY KEY, value REAL NOT NULL);
        """,
    ),
    (
        2,
        """
        -- Device configuration (task T047): each row = one transport×profile device.
        CREATE TABLE devices (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            vendor        TEXT NOT NULL DEFAULT '',
            profile       TEXT NOT NULL DEFAULT '',
            transport     TEXT NOT NULL DEFAULT 'dummy',
            params        TEXT NOT NULL DEFAULT '{}',   -- JSON transport params
            poll_interval REAL,
            bms_topology  TEXT NOT NULL DEFAULT 'inverter',
            enabled       INTEGER NOT NULL DEFAULT 1
        );
        """,
    ),
    (
        3,
        """
        -- Application config as JSON blobs by key: 'tariff', 'economics', 'site',
        -- 'arrays' (tasks T051/T052/T064). One row per config section.
        CREATE TABLE app_config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """,
    ),
]

SCHEMA_VERSION = MIGRATIONS[-1][0]


def run_migrations(conn: sqlite3.Connection) -> int:
    """Apply any unapplied migrations in order. Returns the resulting schema version."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        current = 0
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
    else:
        current = row[0]
    for version, sql in MIGRATIONS:
        if version > current:
            conn.executescript(sql)
            conn.execute("UPDATE schema_version SET version = ?", (version,))
            current = version
    conn.commit()
    return current

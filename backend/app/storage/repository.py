"""Repository over SQLite (plan.md §5; tasks T040/T042/T043/T044/T047).

`SqliteHistoryRepository` persists the poller's readings, rolls raw samples up into
5m/1h/1d buckets, serves history queries, and prunes raw past its retention window.
`DeviceConfigRepository` stores the device list edited via Settings › Devices.

Both share one `AsyncDb` — a sqlite connection pinned to a single dedicated worker thread
(`db.py`) — so every statement runs off the event loop, never touches the connection
concurrently, and is naturally serialized. SQL lives only here — callers see dataclasses
and dicts (the repository abstraction the rest of the app depends on).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from ..aggregator import INTERVALS, bucket_rows
from ..models import Reading
from .db import AsyncDb

# resolution name -> rollup table (None = raw samples).
_TABLES: dict[str, str | None] = {"raw": None, "5m": "rollup_5m", "1h": "rollup_1h", "1d": "rollup_1d"}
_WATERMARK_KEY = "rollup_watermark"


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    ts: float                 # epoch seconds (raw sample time, or bucket start)
    value: float              # raw value, or the bucket average
    min: float | None = None
    max: float | None = None
    last: float | None = None
    n: int | None = None

    def as_dict(self) -> dict:
        d = {"ts": self.ts, "value": self.value}
        if self.n is not None:
            d.update(min=self.min, max=self.max, last=self.last, n=self.n)
        return d


def _is_number(v: object) -> bool:
    # bool is an int subclass but is a status flag, not a measurement — exclude it.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


async def open_repositories(
    path: str,
) -> tuple[
    "SqliteHistoryRepository", "DeviceConfigRepository", "AppConfigRepository",
    "AuditRepository", "AlertRepository",
]:
    """Open ONE connection (single DB thread) and build the repositories on it, so the
    app has a single SQLite handle. Use this from the app; the per-class `.open()` helpers
    are for standalone use/tests."""
    db = await AsyncDb().open(path)
    return (
        SqliteHistoryRepository(db),
        DeviceConfigRepository(db),
        AppConfigRepository(db),
        AuditRepository(db),
        AlertRepository(db),
    )


class AlertRepository:
    """Alert rules + fired-alert events (plan.md §15; tasks T080/T082). Shares the DB."""

    def __init__(self, db: AsyncDb) -> None:
        self._db = db

    @property
    def _conn(self):
        return self._db.conn

    @classmethod
    async def open(cls, path: str) -> "AlertRepository":
        return cls(await AsyncDb().open(path))

    # --- rules ------------------------------------------------------------------
    async def list_rules(self) -> list[dict]:
        rows = await self._db.run(
            lambda: self._conn.execute("SELECT config FROM alert_rules").fetchall()
        )
        return [json.loads(r["config"]) for r in rows]

    async def upsert_rule(self, rule: Mapping) -> None:
        rid, payload = str(rule["id"]), json.dumps(dict(rule))

        def _set():
            self._conn.execute(
                "INSERT INTO alert_rules (id, config) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET config=excluded.config",
                (rid, payload),
            )
            self._conn.commit()

        await self._db.run(_set)

    async def delete_rule(self, rule_id: str) -> bool:
        def _del():
            cur = self._conn.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,))
            self._conn.commit()
            return cur.rowcount

        return await self._db.run(_del) > 0

    async def seed_rules(self, rules: list[Mapping]) -> None:
        """Insert default rules only when none exist (idempotent first-run seeding)."""
        existing = await self._db.run(
            lambda: self._conn.execute("SELECT COUNT(*) AS c FROM alert_rules").fetchone()["c"]
        )
        if existing == 0:
            for r in rules:
                await self.upsert_rule(r)

    # --- fired alerts -----------------------------------------------------------
    async def insert_alert(
        self, *, rule_id, device_id, severity, metric, value, message, fired_at,
    ) -> int:
        def _ins():
            cur = self._conn.execute(
                "INSERT INTO alerts (rule_id, device_id, severity, metric, value, message, fired_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rule_id, device_id, severity, metric, value, message, fired_at),
            )
            self._conn.commit()
            return cur.lastrowid

        return await self._db.run(_ins)

    async def clear_active(self, rule_id: str, device_id: str | None, cleared_at: float) -> int:
        """Mark the open alert(s) for this rule+device cleared. Returns rows updated."""
        def _clear():
            cur = self._conn.execute(
                "UPDATE alerts SET cleared_at=? WHERE rule_id=? AND cleared_at IS NULL "
                "AND (device_id IS ? OR device_id=?)",
                (cleared_at, rule_id, device_id, device_id),
            )
            self._conn.commit()
            return cur.rowcount

        return await self._db.run(_clear)

    async def list_alerts(self, *, active_only: bool = False, limit: int = 100) -> list[dict]:
        def _q():
            sql = "SELECT * FROM alerts"
            if active_only:
                sql += " WHERE cleared_at IS NULL"
            sql += " ORDER BY fired_at DESC LIMIT ?"
            return self._conn.execute(sql, (int(limit),)).fetchall()

        return [dict(r) for r in await self._db.run(_q)]

    async def active_count(self) -> int:
        return await self._db.run(
            lambda: self._conn.execute(
                "SELECT COUNT(*) AS c FROM alerts WHERE cleared_at IS NULL AND acked_at IS NULL"
            ).fetchone()["c"]
        )

    async def ack(self, alert_id: int, ts: float) -> bool:
        def _a():
            cur = self._conn.execute("UPDATE alerts SET acked_at=? WHERE id=?", (ts, alert_id))
            self._conn.commit()
            return cur.rowcount

        return await self._db.run(_a) > 0

    async def snooze(self, alert_id: int, until: float) -> bool:
        def _s():
            cur = self._conn.execute("UPDATE alerts SET snooze_until=? WHERE id=?", (until, alert_id))
            self._conn.commit()
            return cur.rowcount

        return await self._db.run(_s) > 0


class AuditRepository:
    """Append-only log of settings writes (plan.md §12 rule 6; task T078). Shares the DB."""

    def __init__(self, db: AsyncDb) -> None:
        self._db = db

    @property
    def _conn(self):
        return self._db.conn

    @classmethod
    async def open(cls, path: str) -> "AuditRepository":
        return cls(await AsyncDb().open(path))

    async def record(
        self, ts: float, device_id: str, section: str, changes: Mapping, result: str,
        *, slot: int | None = None, source: str = "",
    ) -> None:
        payload = json.dumps(changes)

        def _insert():
            self._conn.execute(
                "INSERT INTO audit (ts, device_id, source, section, slot, changes, result) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, device_id, source, section, slot, payload, result),
            )
            self._conn.commit()

        await self._db.run(_insert)

    async def list(self, *, device_id: str | None = None, limit: int = 100) -> list[dict]:
        """Most-recent writes first (optionally for one device)."""
        def _query():
            sql = "SELECT ts, device_id, source, section, slot, changes, result FROM audit"
            params: list = []
            if device_id is not None:
                sql += " WHERE device_id = ?"
                params.append(device_id)
            sql += " ORDER BY ts DESC LIMIT ?"
            params.append(int(limit))
            return self._conn.execute(sql, params).fetchall()

        rows = await self._db.run(_query)
        return [
            {**dict(r), "changes": json.loads(r["changes"])} for r in rows
        ]


class AppConfigRepository:
    """JSON config sections by key (tariff, economics, site, arrays). Shares the DB."""

    def __init__(self, db: AsyncDb) -> None:
        self._db = db

    @property
    def _conn(self):
        return self._db.conn

    @classmethod
    async def open(cls, path: str) -> "AppConfigRepository":
        return cls(await AsyncDb().open(path))

    async def get(self, key: str, default=None):
        row = await self._db.run(
            lambda: self._conn.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
        )
        return json.loads(row["value"]) if row else default

    async def set(self, key: str, value) -> None:
        payload = json.dumps(value)

        def _set():
            self._conn.execute(
                "INSERT INTO app_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, payload),
            )
            self._conn.commit()

        await self._db.run(_set)

    async def delete(self, key: str) -> bool:
        """Remove a config key. Returns True if a row was deleted."""

        def _delete():
            cur = self._conn.execute("DELETE FROM app_config WHERE key=?", (key,))
            self._conn.commit()
            return cur.rowcount > 0

        return await self._db.run(_delete)

    async def list_prefix(self, prefix: str) -> dict:
        """All {key: value} pairs whose key starts with `prefix` (LIKE wildcards escaped)."""
        like = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

        def _list():
            rows = self._conn.execute(
                "SELECT key, value FROM app_config WHERE key LIKE ? ESCAPE '\\'", (like,)
            ).fetchall()
            return {row["key"]: json.loads(row["value"]) for row in rows}

        return await self._db.run(_list)


class SqliteHistoryRepository:
    """Time-series persistence + rollups + retention."""

    def __init__(self, db: AsyncDb) -> None:
        self._db = db

    @property
    def _conn(self):
        return self._db.conn

    @classmethod
    async def open(cls, path: str) -> "SqliteHistoryRepository":
        return cls(await AsyncDb().open(path))

    # --- writes (T042) ----------------------------------------------------------
    async def write_reading(self, reading: Reading) -> int:
        """Persist the numeric metrics of one reading. Returns the number stored
        (non-numeric metrics — status strings, fault-code lists — are skipped)."""
        ts = reading.ts.timestamp()
        rows = [
            (ts, reading.device_id, metric, float(value))
            for metric, value in reading.metrics.items()
            if _is_number(value)
        ]
        if not rows:
            return 0
        await self._db.run(self._insert_samples, rows)
        return len(rows)

    def _insert_samples(self, rows: list[tuple]) -> None:
        self._conn.executemany(
            "INSERT INTO samples (ts, device_id, metric, value) VALUES (?, ?, ?, ?)", rows
        )
        self._conn.commit()

    # --- rollups (T043) ---------------------------------------------------------
    async def aggregate(self) -> dict[str, int]:
        """Roll raw samples into 5m/1h/1d buckets. Recomputes from the start of the day
        containing the watermark so in-progress buckets stay correct as samples arrive,
        then advances the watermark. Returns the bucket count written per resolution."""
        return await self._db.run(self._aggregate)

    def _aggregate(self) -> dict[str, int]:
        wm = self._get_meta(_WATERMARK_KEY, 0.0)
        # Recompute the whole day around the watermark — cheap (raw retention is short)
        # and keeps the current 5m/1h/1d buckets accurate via upsert.
        start = float(int(wm // INTERVALS["1d"]) * INTERVALS["1d"])
        cur = self._conn.execute(
            "SELECT ts, device_id, metric, value FROM samples WHERE ts >= ? ORDER BY ts", (start,)
        )
        rows = [(r["ts"], r["device_id"], r["metric"], r["value"]) for r in cur.fetchall()]
        written: dict[str, int] = {}
        max_ts = wm
        for name, interval in INTERVALS.items():
            buckets = bucket_rows(rows, interval)
            self._conn.executemany(
                f"""INSERT INTO rollup_{name} (bucket, device_id, metric, avg, min, max, last, n)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bucket, device_id, metric) DO UPDATE SET
                      avg=excluded.avg, min=excluded.min, max=excluded.max,
                      last=excluded.last, n=excluded.n""",
                [(b.bucket, b.device_id, b.metric, b.avg, b.min, b.max, b.last, b.n) for b in buckets],
            )
            written[name] = len(buckets)
        for ts, *_ in rows:
            max_ts = max(max_ts, ts)
        self._set_meta(_WATERMARK_KEY, max_ts)
        self._conn.commit()
        return written

    # --- queries (T044) ---------------------------------------------------------
    async def query(
        self, device_id: str, metric: str, start: float, end: float, resolution: str = "raw"
    ) -> list[SeriesPoint]:
        if resolution not in _TABLES:
            raise ValueError(f"Unknown resolution {resolution!r}; expected one of {list(_TABLES)}")
        return await self._db.run(self._query, device_id, metric, start, end, resolution)

    def _query(self, device_id, metric, start, end, resolution) -> list[SeriesPoint]:
        table = _TABLES[resolution]
        if table is None:
            cur = self._conn.execute(
                "SELECT ts, value FROM samples WHERE device_id=? AND metric=? AND ts BETWEEN ? AND ? ORDER BY ts",
                (device_id, metric, start, end),
            )
            return [SeriesPoint(r["ts"], r["value"]) for r in cur.fetchall()]
        cur = self._conn.execute(
            f"SELECT bucket, avg, min, max, last, n FROM {table} "
            "WHERE device_id=? AND metric=? AND bucket BETWEEN ? AND ? ORDER BY bucket",
            (device_id, metric, start, end),
        )
        return [
            SeriesPoint(r["bucket"], r["avg"], r["min"], r["max"], r["last"], r["n"])
            for r in cur.fetchall()
        ]

    async def metrics(self, device_id: str) -> list[str]:
        """Distinct metric names recorded for a device (drives the History picker)."""
        return await self._db.run(self._metrics, device_id)

    def _metrics(self, device_id: str) -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT metric FROM samples WHERE device_id=? ORDER BY metric", (device_id,)
        )
        return [r["metric"] for r in cur.fetchall()]

    async def latest(self, device_id: str, metric: str) -> float | None:
        return await self._db.run(self._latest, device_id, metric)

    def _latest(self, device_id: str, metric: str) -> float | None:
        cur = self._conn.execute(
            "SELECT value FROM samples WHERE device_id=? AND metric=? ORDER BY ts DESC LIMIT 1",
            (device_id, metric),
        )
        row = cur.fetchone()
        return row["value"] if row else None

    # --- retention (T043) -------------------------------------------------------
    async def prune(self, before_ts: float) -> int:
        """Delete raw samples older than `before_ts` (rollups are kept). Returns rows
        removed. Always aggregate before pruning so the rollups already hold the data."""
        return await self._db.run(self._prune, before_ts)

    def _prune(self, before_ts: float) -> int:
        cur = self._conn.execute("DELETE FROM samples WHERE ts < ?", (before_ts,))
        self._conn.commit()
        return cur.rowcount

    async def rollup_watermark(self) -> float:
        """Epoch seconds of the last-aggregated sample (0 if none) — diagnostics rollup lag."""
        return await self._db.run(self._get_meta, _WATERMARK_KEY, 0.0)

    # --- grid-outage event log (T095) -------------------------------------------
    async def insert_grid_event(self, ts: float, device_id: str, event: str) -> None:
        def _ins():
            self._conn.execute(
                "INSERT INTO grid_events (ts, device_id, event) VALUES (?, ?, ?)",
                (ts, device_id, event),
            )
            self._conn.commit()

        await self._db.run(_ins)

    async def list_grid_events(self, *, limit: int = 100) -> list[dict]:
        rows = await self._db.run(
            lambda: self._conn.execute(
                "SELECT ts, device_id, event FROM grid_events ORDER BY ts DESC LIMIT ?", (int(limit),)
            ).fetchall()
        )
        return [dict(r) for r in rows]

    # --- backup / restore (T091) ------------------------------------------------
    async def backup_bytes(self) -> bytes:
        """A consistent snapshot of the whole database (samples, rollups, config, alerts…)."""
        return await self._db.backup_bytes()

    async def restore(self, data: bytes) -> None:
        """Replace the live database with a validated backup (caller validates the bytes)."""
        await self._db.restore(data)

    # --- meta helpers -----------------------------------------------------------
    def _get_meta(self, key: str, default: float) -> float:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def _set_meta(self, key: str, value: float) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    async def close(self) -> None:
        await self._db.close()


class DeviceConfigRepository:
    """CRUD for configured devices (Settings › Devices, task T047). Shares the same DB."""

    _FIELDS = ("id", "name", "vendor", "profile", "transport", "params", "poll_interval",
               "bms_topology", "enabled")

    def __init__(self, db: AsyncDb) -> None:
        self._db = db

    @property
    def _conn(self):
        return self._db.conn

    @classmethod
    async def open(cls, path: str) -> "DeviceConfigRepository":
        return cls(await AsyncDb().open(path))

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        d["params"] = json.loads(d.get("params") or "{}")
        d["enabled"] = bool(d["enabled"])
        return d

    async def list(self) -> list[dict]:
        rows = await self._db.run(
            lambda: self._conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
        )
        return [self._row_to_dict(r) for r in rows]

    async def get(self, device_id: str) -> dict | None:
        row = await self._db.run(
            lambda: self._conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        )
        return self._row_to_dict(row) if row else None

    async def create(self, device: Mapping) -> dict:
        rec = self._normalize(device)
        await self._db.run(self._insert, rec)
        return self._row_to_dict_from_rec(rec)

    def _insert(self, rec: dict) -> None:
        self._conn.execute(
            """INSERT INTO devices (id, name, vendor, profile, transport, params,
                                    poll_interval, bms_topology, enabled)
               VALUES (:id, :name, :vendor, :profile, :transport, :params,
                       :poll_interval, :bms_topology, :enabled)""",
            rec,
        )
        self._conn.commit()

    async def update(self, device_id: str, fields: Mapping) -> dict | None:
        existing = await self.get(device_id)
        if existing is None:
            return None
        merged = {**existing, **{k: v for k, v in fields.items() if k in self._FIELDS}}
        merged["id"] = device_id
        rec = self._normalize(merged)
        await self._db.run(self._update, rec)
        return self._row_to_dict_from_rec(rec)

    def _update(self, rec: dict) -> None:
        self._conn.execute(
            """UPDATE devices SET name=:name, vendor=:vendor, profile=:profile,
                   transport=:transport, params=:params, poll_interval=:poll_interval,
                   bms_topology=:bms_topology, enabled=:enabled WHERE id=:id""",
            rec,
        )
        self._conn.commit()

    async def delete(self, device_id: str) -> bool:
        def _delete():
            cur = self._conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
            self._conn.commit()
            return cur.rowcount
        return await self._db.run(_delete) > 0

    async def count(self) -> int:
        row = await self._db.run(
            lambda: self._conn.execute("SELECT COUNT(*) AS c FROM devices").fetchone()
        )
        return row["c"]

    @staticmethod
    def _normalize(device: Mapping) -> dict:
        params = device.get("params", {})
        return {
            "id": str(device["id"]),
            "name": str(device.get("name") or device["id"]),
            "vendor": str(device.get("vendor", "")),
            "profile": str(device.get("profile", "")),
            "transport": str(device.get("transport", "dummy")),
            "params": params if isinstance(params, str) else json.dumps(params),
            "poll_interval": device.get("poll_interval"),
            "bms_topology": str(device.get("bms_topology", "inverter")),
            "enabled": 1 if device.get("enabled", True) else 0,
        }

    @staticmethod
    def _row_to_dict_from_rec(rec: dict) -> dict:
        d = dict(rec)
        d["params"] = json.loads(d["params"]) if isinstance(d["params"], str) else d["params"]
        d["enabled"] = bool(d["enabled"])
        return d

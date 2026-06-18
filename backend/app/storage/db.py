"""SQLite connection helper (plan.md §5).

One place that opens a correctly-configured connection: WAL for concurrent reads while
the poller writes, a Row factory so repositories get dict-like rows, and
`check_same_thread=False` because async handlers run DB work in a thread pool
(`asyncio.to_thread`) guarded by an `asyncio.Lock` in the repository.
"""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL: readers don't block the poller's writes (and vice-versa) on the Pi.
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class AsyncDb:
    """A sqlite connection bound to a single dedicated worker thread.

    Every statement runs on that one thread via a 1-worker executor, so the connection
    is never touched concurrently (the correct sqlite+asyncio pattern) and all DB work is
    naturally serialized — no extra lock needed, and no cross-thread/close races that can
    crash the native sqlite extension. Shared by the history and device-config repos so
    the app keeps a single handle."""

    def __init__(self) -> None:
        self._ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite")
        self.conn: sqlite3.Connection | None = None

    async def open(self, path: str) -> "AsyncDb":
        from .migrations import run_migrations

        self.conn = await self.run(connect, path)
        await self.run(run_migrations, self.conn)
        return self

    async def run(self, fn, *args):
        """Run a blocking DB callable on the dedicated thread and await its result."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._ex, fn, *args)

    async def close(self) -> None:
        if self.conn is not None:
            conn, self.conn = self.conn, None
            await self.run(conn.close)
        self._ex.shutdown(wait=True)

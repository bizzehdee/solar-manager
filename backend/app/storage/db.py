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
        self._path: str | None = None

    async def open(self, path: str) -> "AsyncDb":
        from .migrations import run_migrations

        self._path = path
        self.conn = await self.run(connect, path)
        await self.run(run_migrations, self.conn)
        return self

    @property
    def path(self) -> str | None:
        return self._path

    async def backup_bytes(self) -> bytes:
        """A consistent snapshot of the whole DB as bytes (`VACUUM INTO` a temp file on the
        DB thread, so it's atomic w.r.t. other queries). Works for file + in-memory DBs."""
        import os
        import tempfile

        def _dump() -> bytes:
            fd, tmp = tempfile.mkstemp(suffix=".sqlite")
            os.close(fd)
            os.unlink(tmp)  # VACUUM INTO requires the target not to exist
            try:
                self.conn.execute("VACUUM INTO ?", (tmp,))
                with open(tmp, "rb") as fh:
                    return fh.read()
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)

        return await self.run(_dump)

    async def restore(self, data: bytes) -> None:
        """Replace the live database with an uploaded snapshot (T091). Validated by the
        caller; here we atomically (on the single DB thread) close, overwrite the file, and
        reopen + migrate — repos read `self.conn` via a property, so they pick up the new
        handle. Not supported for in-memory DBs."""
        from .migrations import run_migrations

        if not self._path or self._path == ":memory:":
            raise ValueError("restore requires a file-backed database")
        path = self._path

        def _swap() -> sqlite3.Connection:
            self.conn.close()
            for suffix in ("-wal", "-shm"):  # drop stale WAL sidecars from the old DB
                try:
                    import os

                    os.path.exists(path + suffix) and os.unlink(path + suffix)
                except OSError:
                    pass
            with open(path, "wb") as fh:
                fh.write(data)
            conn = connect(path)
            run_migrations(conn)
            return conn

        self.conn = await self.run(_swap)

    async def run(self, fn, *args):
        """Run a blocking DB callable on the dedicated thread and await its result."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._ex, fn, *args)

    async def close(self) -> None:
        if self.conn is not None:
            conn, self.conn = self.conn, None
            await self.run(conn.close)
        self._ex.shutdown(wait=True)

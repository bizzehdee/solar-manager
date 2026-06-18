"""Backup / restore / CSV export (plan.md §19 / T091)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

_BASE = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def _client(db_path: str) -> TestClient:
    return TestClient(create_app(settings=Settings(poll_interval_s=60, db_path=db_path, persist_interval_s=3600),
                                 clock=lambda: _BASE))


def test_backup_downloads_a_sqlite_snapshot(tmp_path):
    with _client(str(tmp_path / "sv.db")) as client:
        r = client.get("/api/backup")
        assert r.status_code == 200
        assert r.content.startswith(b"SQLite format 3\x00")
        assert "attachment" in r.headers["content-disposition"]


def test_restore_roundtrips_a_backup(tmp_path):
    with _client(str(tmp_path / "sv.db")) as client:
        backup = client.get("/api/backup").content
        r = client.post("/api/restore", files={"file": ("b.sqlite", backup, "application/x-sqlite3")})
        assert r.status_code == 200 and r.json()["ok"] is True
        # App still works after the live DB was swapped.
        assert client.get("/api/alert-rules").status_code == 200


def test_restore_rejects_non_database(tmp_path):
    with _client(str(tmp_path / "sv.db")) as client:
        r = client.post("/api/restore", files={"file": ("x.txt", b"not a database", "text/plain")})
        assert r.status_code == 422


def test_restore_rejects_in_memory_db():
    with _client(":memory:") as client:
        backup = client.get("/api/backup").content  # backup works for :memory:
        r = client.post("/api/restore", files={"file": ("b.sqlite", backup, "application/x-sqlite3")})
        assert r.status_code == 400  # but restore needs a file-backed DB


def test_export_csv_has_header_and_content_type(tmp_path):
    with _client(str(tmp_path / "sv.db")) as client:
        r = client.get("/api/export", params={"metric": "battery_soc_pct"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert r.text.splitlines()[0] == "ts,iso,value,min,max,last,n"

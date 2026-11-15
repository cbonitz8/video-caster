"""SQLite watch history."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

SCHEMA = """\
CREATE TABLE IF NOT EXISTS watch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    device_id TEXT,
    device_name TEXT,
    started_at REAL NOT NULL,
    last_updated_at REAL NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    position REAL NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_history_file ON watch_history(file_path);
CREATE INDEX IF NOT EXISTS idx_history_updated ON watch_history(last_updated_at DESC);

"""

POSITION_WRITE_INTERVAL = 5.0

T = TypeVar("T")


@dataclass
class WatchRecord:
    id: int
    file_path: str
    file_name: str
    device_id: str
    device_name: str
    started_at: float
    last_updated_at: float
    duration: float
    position: float
    completed: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> WatchRecord:
        return cls(
            id=row["id"], file_path=row["file_path"], file_name=row["file_name"],
            device_id=row["device_id"], device_name=row["device_name"],
            started_at=row["started_at"], last_updated_at=row["last_updated_at"],
            duration=row["duration"], position=row["position"], completed=bool(row["completed"]),
        )


class HistoryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._last_position_write: dict[int, float] = {}

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    async def _run(self, work: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(lambda: work(self._get_conn()))

    async def _write(self, sql: str, params: tuple) -> None:
        def write(conn: sqlite3.Connection) -> None:
            conn.execute(sql, params)
            conn.commit()
        await self._run(write)

    async def record_play(self, file_path: str, file_name: str, device_id: str,
                          device_name: str, duration: float) -> int:
        """The file's unfinished row, refreshed, or a new one."""
        def record(conn: sqlite3.Connection) -> int:
            now = time.time()
            row = conn.execute(
                "SELECT id FROM watch_history WHERE file_path = ? AND completed = 0 "
                "ORDER BY last_updated_at DESC LIMIT 1",
                (file_path,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE watch_history SET device_id=?, device_name=?, last_updated_at=?, duration=? WHERE id=?",
                    (device_id, device_name, now, duration, row["id"]),
                )
                conn.commit()
                return row["id"]
            cur = conn.execute(
                "INSERT INTO watch_history (file_path, file_name, device_id, device_name, "
                "started_at, last_updated_at, duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (file_path, file_name, device_id, device_name, now, now, duration),
            )
            conn.commit()
            return cur.lastrowid
        return await self._run(record)

    async def update_position(self, watch_id: int, position: float) -> None:
        """Save position at most every POSITION_WRITE_INTERVAL seconds per row."""
        now = time.time()
        if now - self._last_position_write.get(watch_id, 0.0) < POSITION_WRITE_INTERVAL:
            return
        self._last_position_write[watch_id] = now
        await self._write("UPDATE watch_history SET position=?, last_updated_at=? WHERE id=?",
                          (position, now, watch_id))

    async def force_update_position(self, watch_id: int, position: float) -> None:
        """Save position immediately, bypassing the throttle."""
        await self._write("UPDATE watch_history SET position=?, last_updated_at=? WHERE id=?",
                          (position, time.time(), watch_id))

    async def update_duration(self, watch_id: int, duration: float) -> None:
        """Set the duration if it was initially unknown (0)."""
        await self._write("UPDATE watch_history SET duration=? WHERE id=? AND duration=0",
                          (duration, watch_id))

    async def mark_completed(self, watch_id: int) -> None:
        await self._write("UPDATE watch_history SET completed=1, last_updated_at=? WHERE id=?",
                          (time.time(), watch_id))

    async def meaningful_records(self) -> list[WatchRecord]:
        """Completed or started rows, oldest first; rows a cast left at position 0 don't count."""
        def fetch(conn: sqlite3.Connection) -> list[WatchRecord]:
            rows = conn.execute(
                "SELECT * FROM watch_history WHERE completed = 1 OR position > 0 "
                "ORDER BY last_updated_at, id"
            ).fetchall()
            return [WatchRecord.from_row(r) for r in rows]
        return await self._run(fetch)

    async def has_file(self, file_path: str) -> bool:
        """True if the file was ever cast, completed or not."""
        def fetch(conn: sqlite3.Connection) -> bool:
            row = conn.execute("SELECT 1 FROM watch_history WHERE file_path = ? LIMIT 1",
                               (file_path,)).fetchone()
            return row is not None
        return await self._run(fetch)

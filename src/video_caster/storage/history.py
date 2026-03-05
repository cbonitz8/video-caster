"""SQLite watch history and session persistence."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

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

    @property
    def progress(self) -> float:
        if self.duration <= 0:
            return 0.0
        return min(self.position / self.duration, 1.0)


class HistoryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._last_position_update: float = 0.0

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

    async def _run(self, fn, *args):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    # -- Watch history --

    def _record_play(self, file_path: str, file_name: str, device_id: str,
                     device_name: str, duration: float) -> int:
        conn = self._get_conn()
        now = time.time()
        # Check for existing incomplete record for this file
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
        return cur.lastrowid  # type: ignore[return-value]

    async def record_play(self, file_path: str, file_name: str, device_id: str,
                          device_name: str, duration: float) -> int:
        return await self._run(self._record_play, file_path, file_name,
                               device_id, device_name, duration)

    def _update_position(self, watch_id: int, position: float) -> None:
        now = time.time()
        # Throttle to every 5 seconds
        if now - self._last_position_update < 5.0:
            return
        self._last_position_update = now
        conn = self._get_conn()
        conn.execute(
            "UPDATE watch_history SET position=?, last_updated_at=? WHERE id=?",
            (position, now, watch_id),
        )
        conn.commit()

    async def update_position(self, watch_id: int, position: float) -> None:
        await self._run(self._update_position, watch_id, position)

    def _force_update_position(self, watch_id: int, position: float) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE watch_history SET position=?, last_updated_at=? WHERE id=?",
            (position, time.time(), watch_id),
        )
        conn.commit()

    async def force_update_position(self, watch_id: int, position: float) -> None:
        """Save position immediately, bypassing the throttle. Use on quit."""
        await self._run(self._force_update_position, watch_id, position)

    def _update_duration(self, watch_id: int, duration: float) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE watch_history SET duration=? WHERE id=? AND duration=0",
            (duration, watch_id),
        )
        conn.commit()

    async def update_duration(self, watch_id: int, duration: float) -> None:
        """Set the duration if it was initially unknown (0)."""
        await self._run(self._update_duration, watch_id, duration)

    def _mark_completed(self, watch_id: int) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE watch_history SET completed=1, last_updated_at=? WHERE id=?",
            (time.time(), watch_id),
        )
        conn.commit()

    async def mark_completed(self, watch_id: int) -> None:
        await self._run(self._mark_completed, watch_id)

    def _get_continue_watching(self, limit: int = 20) -> list[WatchRecord]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM watch_history WHERE completed = 0 AND position > 0 "
            "ORDER BY last_updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            WatchRecord(
                id=r["id"], file_path=r["file_path"], file_name=r["file_name"],
                device_id=r["device_id"], device_name=r["device_name"],
                started_at=r["started_at"], last_updated_at=r["last_updated_at"],
                duration=r["duration"], position=r["position"],
                completed=bool(r["completed"]),
            )
            for r in rows
        ]

    async def get_continue_watching(self, limit: int = 20) -> list[WatchRecord]:
        return await self._run(self._get_continue_watching, limit)

    def _get_saved_position(self, file_path: str) -> float:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT position FROM watch_history WHERE file_path = ? AND completed = 0 "
            "ORDER BY last_updated_at DESC LIMIT 1",
            (file_path,),
        ).fetchone()
        return row["position"] if row else 0.0

    async def get_saved_position(self, file_path: str) -> float:
        return await self._run(self._get_saved_position, file_path)

    def _get_completed_or_nearly(self, limit: int = 50) -> list[WatchRecord]:
        """Get episodes that are completed or >= 90% watched."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM watch_history "
            "WHERE (completed = 1 OR (duration > 0 AND position / duration >= 0.9)) "
            "ORDER BY last_updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            WatchRecord(
                id=r["id"], file_path=r["file_path"], file_name=r["file_name"],
                device_id=r["device_id"], device_name=r["device_name"],
                started_at=r["started_at"], last_updated_at=r["last_updated_at"],
                duration=r["duration"], position=r["position"],
                completed=bool(r["completed"]),
            )
            for r in rows
        ]

    async def get_completed_or_nearly(self, limit: int = 50) -> list[WatchRecord]:
        return await self._run(self._get_completed_or_nearly, limit)

"""Library views shared by clients: Continue Watching, Up Next, Newly Added."""

from __future__ import annotations

import asyncio
from pathlib import Path

from video_caster.config import Config
from video_caster.storage.episode import find_next_episode, parse_episode
from video_caster.storage.history import HistoryStore
from video_caster.storage.scanner import scan_watch_folders


async def continue_watching(history: HistoryStore, limit: int = 10) -> list[dict]:
    records = await history.get_continue_watching(limit=limit)
    return [
        {
            "path": r.file_path,
            "name": r.file_name,
            "position": r.position,
            "duration": r.duration,
            "progress": r.progress,
        }
        for r in records
    ]


async def up_next(history: HistoryStore) -> list[dict]:
    """Next episode after each completed or nearly-completed one, unless already watched."""
    completed = await history.get_completed_or_nearly(limit=50)
    seen: set[str] = set()
    entries: list[dict] = []
    for rec in completed:
        path = Path(rec.file_path)
        if parse_episode(path) is None:
            continue
        # find_next_episode lists directories; keep slow drives off the event loop.
        nxt = await asyncio.to_thread(find_next_episode, path)
        if nxt is None or str(nxt) in seen:
            continue
        if await history.has_file(str(nxt)):
            continue
        seen.add(str(nxt))
        entries.append({"path": str(nxt), "name": nxt.name, "watched_name": rec.file_name})
    return entries


async def newly_added(config: Config) -> list[dict]:
    files = await scan_watch_folders(config.watch_folders, max_depth=10)
    return [
        {"path": str(f.path), "name": f.name, "size": f.size, "mtime_ago": f.mtime_ago}
        for f in files[: config.recently_added_limit]
    ]

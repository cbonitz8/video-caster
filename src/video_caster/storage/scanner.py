"""Watch folder scanner — finds video files sorted by modification time."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from video_caster.transcoding.formats import VIDEO_EXTENSIONS

log = logging.getLogger(__name__)


@dataclass
class VideoFileInfo:
    path: Path
    name: str
    size: int
    mtime: float

    @property
    def mtime_ago(self) -> str:
        """Human-readable time since modification."""
        import time
        delta = time.time() - self.mtime
        if delta < 3600:
            mins = int(delta / 60)
            return f"{mins}m ago" if mins > 0 else "just now"
        elif delta < 86400:
            return f"{int(delta / 3600)}h ago"
        elif delta < 604800:
            days = int(delta / 86400)
            return f"{days}d ago" if days > 1 else "yesterday"
        else:
            return f"{int(delta / 604800)}w ago"


def _scan_sync(folders: list[Path], extensions: set[str], max_depth: int) -> list[VideoFileInfo]:
    results: list[VideoFileInfo] = []
    for folder in folders:
        if not folder.is_dir():
            log.warning("Watch folder does not exist: %s", folder)
            continue
        for root, dirs, files in os.walk(folder):
            # Enforce max depth
            depth = str(root).count(os.sep) - str(folder).count(os.sep)
            if depth >= max_depth:
                dirs.clear()
                continue
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.startswith("."):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in extensions:
                    full = Path(root) / name
                    try:
                        stat = full.stat()
                        results.append(VideoFileInfo(
                            path=full, name=name,
                            size=stat.st_size, mtime=stat.st_mtime,
                        ))
                    except OSError:
                        continue
    results.sort(key=lambda f: f.mtime, reverse=True)
    return results


async def scan_watch_folders(
    folders: list[Path],
    extensions: set[str] | None = None,
    max_depth: int = 10,
) -> list[VideoFileInfo]:
    """Scan watch folders for video files, returning newest first."""
    exts = extensions or VIDEO_EXTENSIONS
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _scan_sync, folders, exts, max_depth)

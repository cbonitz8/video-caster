"""Which files the tailnet may see: watch folders only, resolved."""

from __future__ import annotations

import logging
from pathlib import Path

from video_caster.titles import display_title
from video_caster.transcoding.formats import VIDEO_EXTENSIONS

log = logging.getLogger(__name__)


def is_under(path: Path, folders: list[Path]) -> bool:
    # resolve() follows symlinks and collapses "..", so neither can lead out.
    resolved = path.resolve()
    return any(resolved.is_relative_to(folder.resolve()) for folder in folders)


def watch_roots(folders: list[Path]) -> list[dict]:
    return [{"path": str(f), "name": f.name, "is_dir": True} for f in folders if f.is_dir()]


def list_folder(target: Path) -> list[dict]:
    entries: list[dict] = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            entries.append({"path": str(child), "name": child.name, "is_dir": True})
        elif child.suffix.lower() in VIDEO_EXTENSIONS:
            try:
                size = child.stat().st_size
            except OSError as e:
                # e.g. a symlink into a drive that isn't plugged in
                log.warning("Skipping unreadable file %s: %s", child, e)
                continue
            entries.append({
                "path": str(child), "name": child.name, "is_dir": False, "size": size,
                **display_title(child),
            })
    return entries

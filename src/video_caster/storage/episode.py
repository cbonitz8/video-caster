"""Episode detection and next-episode suggestion."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from video_caster.transcoding.formats import VIDEO_EXTENSIONS

log = logging.getLogger(__name__)

# Patterns: S01E03, s01e03, 1x03, etc.
_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})"),          # S01E03
    re.compile(r"(\d{1,2})[xX](\d{1,3})"),               # 1x03
    re.compile(r"[Ss]eason\s*(\d{1,2}).*[Ee]pisode\s*(\d{1,3})", re.IGNORECASE),
]

# Directory-based: "Season 1/Episode 03.mkv" or "Season 1/03 - title.mkv"
_DIR_SEASON = re.compile(r"[Ss]eason\s*(\d{1,2})")
_DIR_EPISODE = re.compile(r"(?:[Ee]pisode\s*|[Ee]p?\s*|^)(\d{1,3})")


@dataclass
class EpisodeInfo:
    season: int
    episode: int
    path: Path


def parse_episode(path: Path) -> EpisodeInfo | None:
    """Try to extract season/episode from a file path."""
    name = path.stem

    # Try filename patterns first
    for pattern in _PATTERNS:
        m = pattern.search(name)
        if m:
            return EpisodeInfo(season=int(m.group(1)), episode=int(m.group(2)), path=path)

    # Try directory-based detection
    parent = path.parent.name
    season_match = _DIR_SEASON.search(parent)
    if season_match:
        ep_match = _DIR_EPISODE.search(name)
        if ep_match:
            return EpisodeInfo(
                season=int(season_match.group(1)),
                episode=int(ep_match.group(1)),
                path=path,
            )

    return None


def _list_dir(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError as e:
        log.warning("Skipping unreadable directory %s: %s", directory, e)
        return []


def find_next_episode(current: Path, directory: Path | None = None) -> Path | None:
    """Find the next episode after `current` in the same directory (or parent)."""
    info = parse_episode(current)
    if not info:
        return None

    search_dir = directory or current.parent
    if not search_dir.is_dir():
        return None

    # Only climb to sibling season dirs from a season dir: a flat folder like
    # ~/Movies would otherwise walk all of $HOME (incl. TCC-blocked ~/.Trash).
    dirs_to_scan = [search_dir]
    if _DIR_SEASON.search(search_dir.name):
        for sibling in _list_dir(search_dir.parent):
            if sibling != search_dir and sibling.is_dir() and _DIR_SEASON.search(sibling.name):
                dirs_to_scan.append(sibling)

    candidates: list[EpisodeInfo] = []
    for sdir in dirs_to_scan:
        for child in _list_dir(sdir):
            if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
                ep = parse_episode(child)
                if ep:
                    candidates.append(ep)

    # Find next: same season + 1 episode, or next season episode 1
    next_same_season = [
        c for c in candidates
        if c.season == info.season and c.episode == info.episode + 1
    ]
    if next_same_season:
        return next_same_season[0].path

    next_season = [
        c for c in candidates
        if c.season == info.season + 1 and c.episode == 1
    ]
    if next_season:
        return next_season[0].path

    return None

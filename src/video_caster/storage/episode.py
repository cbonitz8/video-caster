"""Episode detection from file and folder names."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})"),
    re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,3})(?!\d)"),  # 1x03, not 1920x1080
    re.compile(r"[Ss]eason\s*(\d{1,2}).*[Ee]pisode\s*(\d{1,3})", re.IGNORECASE),
]

_DIR_SEASON = re.compile(r"[Ss]eason\s*(\d{1,2})")
_DIR_EPISODE = re.compile(r"(?:[Ee]pisode\s*|[Ee]p?\s*|^)(\d{1,3})")


@dataclass
class EpisodeInfo:
    season: int
    episode: int


@dataclass
class _Marker:
    info: EpisodeInfo
    before: str
    after: str


def _marker(path: Path) -> _Marker | None:
    name = path.stem
    for pattern in _PATTERNS:
        m = pattern.search(name)
        if m:
            return _Marker(EpisodeInfo(int(m.group(1)), int(m.group(2))), name[: m.start()], name[m.end():])
    season = _DIR_SEASON.search(path.parent.name)
    if season:
        m = _DIR_EPISODE.search(name)
        if m:
            return _Marker(EpisodeInfo(int(season.group(1)), int(m.group(1))), "", name[m.end():])
    return None


def parse_episode(path: Path) -> EpisodeInfo | None:
    marker = _marker(path)
    return None if marker is None else marker.info


def split_episode_name(path: Path) -> tuple[str, str] | None:
    """The stem's text before and after its season/episode marker."""
    marker = _marker(path)
    return None if marker is None else (marker.before, marker.after)

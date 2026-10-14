"""Clean display titles derived from video file names."""

from __future__ import annotations

import re
from pathlib import Path

from video_caster.storage.episode import parse_episode, split_episode_name

_QUALITY = re.compile(
    r"(?<![A-Za-z0-9])(?:480p|720p|1080p|2160p|4k|web-?dl|webrip|bluray|hdtv"
    r"|x26[45]|hevc|h\.?26[45]|ddp?5\.1|aac|10bit)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<![A-Za-z0-9-])(?:19|20)\d{2}(?![A-Za-z0-9-])")
_SEASON_DIR = re.compile(r"[Ss]eason\s*\d{1,2}")


def _before_quality(text: str) -> str:
    match = _QUALITY.search(text)
    return text if match is None else text[: match.start()]


def _clean(text: str) -> str:
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -([")


def _show_folder(path: Path) -> str:
    folder = path.parent.parent if _SEASON_DIR.search(path.parent.name) else path.parent
    return _clean(folder.name)


def display_title(path: Path) -> dict:
    stem = path.stem
    cleaned = _clean(stem)
    fallback = cleaned if cleaned else stem

    info = parse_episode(path)
    split = split_episode_name(path)
    if info is not None and split is not None:
        before, after = split
        show = _clean(before)
        if not show:
            show = _show_folder(path)
        if not show:
            show = fallback
        code = f"S{info.season:02d}E{info.episode:02d}"
        name = _clean(_before_quality(after))
        return {"title": show, "subtitle": f"{code} · {name}" if name else code}

    head = _before_quality(stem)
    years = [m for m in _YEAR.finditer(head) if m.start() > 0]
    if years:
        year = years[-1]
        name = _clean(head[: year.start()])
        if name:
            return {"title": f"{name} ({year.group()})", "subtitle": None}
    title = _clean(head)
    return {"title": title if title else fallback, "subtitle": None}

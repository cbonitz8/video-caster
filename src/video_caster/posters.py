"""Hand-picked show and movie art in the settings folder: <slug>.jpg (2:3) and <slug>-wide.jpg (16:9)."""

from __future__ import annotations

import re
from pathlib import Path

from video_caster.config import CONFIG_DIR

POSTERS_DIR = CONFIG_DIR / "posters"
ART_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slug(title: str) -> str:
    return _NON_SLUG.sub("-", title.lower()).strip("-")


def is_art_name(name: str) -> bool:
    if any(c in name for c in "/\\\0") or name.startswith("."):
        return False
    return Path(name).suffix.lower() in ART_EXTENSIONS


def art_index(posters_dir: Path) -> dict[str, str]:
    if not posters_dir.is_dir():
        return {}
    found: dict[str, tuple[int, str]] = {}
    for f in posters_dir.iterdir():
        if not is_art_name(f.name) or not f.is_file():
            continue
        rank = ART_EXTENSIONS.index(f.suffix.lower())
        if f.stem in found and found[f.stem][0] <= rank:
            continue
        found[f.stem] = (rank, f"/posters/{f.name}?v={int(f.stat().st_mtime)}")
    return {stem: url for stem, (_, url) in found.items()}


def art_for(index: dict[str, str], title: str) -> dict:
    s = slug(title)
    if s == "":
        return {"slug": s, "poster": None, "wide": None}
    return {"slug": s, "poster": index.get(s), "wide": index.get(f"{s}-wide")}

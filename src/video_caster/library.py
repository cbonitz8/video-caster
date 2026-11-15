"""Library shelves shared by clients: Continue Watching, Shows, Movies, Newly Added."""

from __future__ import annotations

import asyncio
from pathlib import Path

from video_caster.catalogue import Catalogue, Episode, WatchStates, is_watched
from video_caster.config import Config
from video_caster.posters import art_for, art_index
from video_caster.storage.history import HistoryStore
from video_caster.storage.scanner import scan_watch_folders
from video_caster.titles import display_title

CONTINUE_LIMIT = 20


def _row(path: Path, states: WatchStates) -> dict:
    rec = states.of(path)
    watched = rec is not None and is_watched(rec)
    in_progress = rec is not None and not watched
    return {
        "path": str(path),
        "name": path.name,
        **display_title(path),
        "position": rec.position if in_progress else None,
        "duration": rec.duration if in_progress else None,
        "watched": watched,
    }


def _show(catalogue: Catalogue, key: str, states: WatchStates, art: dict[str, str]) -> tuple[dict, dict | None, float | None]:
    eps: list[Episode] = catalogue.shows[key]
    title = display_title(eps[0].path)["title"]
    pick, active = catalogue.next_pick(key, states)
    if pick is None:
        pick = next((e.path for e in eps if not states.is_watched(e.path)), None)
        tile = None
    else:
        tile = {**_row(pick, states), "title": title, **art_for(art, title)}
    seasons: dict[int, list[dict]] = {}
    for ep in eps:
        seasons.setdefault(ep.key.season, []).append(
            {**_row(ep.path, states), "season": ep.key.season, "episode": ep.key.episode})
    show = {
        "key": key,
        "title": title,
        "episode_count": len(eps),
        "up_next": None if pick is None else _row(pick, states),
        "seasons": [{"season": n, "episodes": rows} for n, rows in seasons.items()],
        **art_for(art, title),
    }
    return show, tile, active


async def build_library(config: Config, history: HistoryStore, posters_dir: Path) -> dict:
    files = await scan_watch_folders(config.watch_folders, max_depth=10)
    states = WatchStates(await history.meaningful_records())
    art = await asyncio.to_thread(art_index, posters_dir)
    catalogue = Catalogue([f.path for f in files])

    shows: list[dict] = []
    tiles: list[tuple[float, dict]] = []
    for key in catalogue.shows:
        show, tile, active = _show(catalogue, key, states, art)
        shows.append(show)
        if tile is not None:
            tiles.append((active, tile))

    movies: list[dict] = []
    for path in catalogue.movies:
        row = {**_row(path, states), **art_for(art, display_title(path)["title"])}
        movies.append(row)
        if row["position"] is not None:
            tiles.append((states.of(path).last_updated_at, row))

    def with_art(path: Path) -> dict:
        return {**_row(path, states), **art_for(art, display_title(path)["title"])}

    tiles.sort(key=lambda t: t[0], reverse=True)
    return {
        "continue": [tile for _, tile in tiles[:CONTINUE_LIMIT]],
        "shows": sorted(shows, key=lambda s: s["title"].casefold()),
        "movies": sorted(movies, key=lambda m: m["title"].casefold()),
        "newly_added": [
            {**with_art(f.path), "mtime_ago": f.mtime_ago}
            for f in files[: config.recently_added_limit]
        ],
    }


async def attach_positions(history: HistoryStore, rows: list[dict]) -> None:
    states = WatchStates(await history.meaningful_records())
    for row in rows:
        row["position"] = states.resume_position(Path(row["path"]))

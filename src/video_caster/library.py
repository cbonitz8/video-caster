"""Library shelves shared by clients: Continue Watching, Shows, Movies, Newly Added."""

from __future__ import annotations

import asyncio
from pathlib import Path

from video_caster.config import Config
from video_caster.posters import art_for, art_index
from video_caster.storage.episode import EpisodeInfo, parse_episode
from video_caster.storage.history import HistoryStore, WatchRecord
from video_caster.storage.scanner import scan_watch_folders
from video_caster.titles import display_title

WATCHED_AT = 0.9
CONTINUE_LIMIT = 20

Episode = tuple[EpisodeInfo, Path]


def _watched(rec: WatchRecord) -> bool:
    return rec.completed or (rec.duration > 0 and rec.position / rec.duration >= WATCHED_AT)


def _row(path: Path, rec: WatchRecord | None) -> dict:
    watched = rec is not None and _watched(rec)
    in_progress = rec is not None and not watched
    return {
        "path": str(path),
        "name": path.name,
        **display_title(path),
        "position": rec.position if in_progress else None,
        "duration": rec.duration if in_progress else None,
        "watched": watched,
    }


def _group(paths: list[Path]) -> tuple[dict[str, list[Episode]], list[Path]]:
    shows: dict[str, list[Episode]] = {}
    movies: list[Path] = []
    for path in paths:
        info = parse_episode(path)
        if info is None:
            movies.append(path)
            continue
        shows.setdefault(display_title(path)["title"].casefold(), []).append((info, path))
    for eps in shows.values():
        eps.sort(key=lambda e: (e[0].season, e[0].episode, str(e[1])))
    return shows, movies


def _is_watched(path: Path, states: dict[str, WatchRecord]) -> bool:
    rec = states.get(str(path))
    return rec is not None and _watched(rec)


def _next_pick(eps: list[Episode], states: dict[str, WatchRecord]) -> tuple[Path | None, float | None]:
    """The episode to continue with and when the show was last active; the pick is None when there is none."""
    touched = [(states[str(p)], info) for info, p in eps if str(p) in states]
    if not touched:
        return None, None
    rec, last = max(touched, key=lambda t: (t[0].last_updated_at, t[0].id))
    if not _watched(rec):
        return Path(rec.file_path), rec.last_updated_at
    for info, path in eps:
        if (info.season, info.episode) > (last.season, last.episode) and not _is_watched(path, states):
            return path, rec.last_updated_at
    return None, rec.last_updated_at


def _show(key: str, eps: list[Episode], states: dict[str, WatchRecord], art: dict[str, str]) -> tuple[dict, dict | None, float | None]:
    title = display_title(eps[0][1])["title"]
    pick, active = _next_pick(eps, states)
    if pick is None:
        pick = next((p for _, p in eps if not _is_watched(p, states)), None)
        tile = None
    else:
        tile = {**_row(pick, states.get(str(pick))), "title": title, **art_for(art, title)}
    seasons: dict[int, list[dict]] = {}
    for info, path in eps:
        seasons.setdefault(info.season, []).append(
            {**_row(path, states.get(str(path))), "season": info.season, "episode": info.episode})
    show = {
        "key": key,
        "title": title,
        "episode_count": len(eps),
        "up_next": None if pick is None else _row(pick, states.get(str(pick))),
        "seasons": [{"season": n, "episodes": rows} for n, rows in seasons.items()],
        **art_for(art, title),
    }
    return show, tile, active


async def build_library(config: Config, history: HistoryStore, posters_dir: Path) -> dict:
    files = await scan_watch_folders(config.watch_folders, max_depth=10)
    states = await history.latest_meaningful([str(f.path) for f in files])
    art = await asyncio.to_thread(art_index, posters_dir)
    shows_by_key, movie_paths = _group([f.path for f in files])

    shows: list[dict] = []
    tiles: list[tuple[float, dict]] = []
    for key, eps in shows_by_key.items():
        show, tile, active = _show(key, eps, states, art)
        shows.append(show)
        if tile is not None:
            tiles.append((active, tile))

    movies: list[dict] = []
    for path in movie_paths:
        rec = states.get(str(path))
        row = {**_row(path, rec), **art_for(art, display_title(path)["title"])}
        movies.append(row)
        if row["position"] is not None:
            tiles.append((rec.last_updated_at, row))

    def with_art(path: Path) -> dict:
        return {**_row(path, states.get(str(path))), **art_for(art, display_title(path)["title"])}

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
    positions = await history.positions_for([row["path"] for row in rows])
    for row in rows:
        row["position"] = positions.get(row["path"])

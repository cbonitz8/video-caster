"""Episode Catalogue: one show identity, one episode order, one "watched" rule."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from video_caster.storage.episode import parse_episode
from video_caster.storage.history import WatchRecord
from video_caster.titles import display_title

WATCHED_AT = 0.9


@dataclass(frozen=True)
class EpisodeKey:
    show: str
    season: int
    episode: int

    @property
    def order(self) -> tuple[int, int]:
        return self.season, self.episode


@dataclass(frozen=True)
class Episode:
    key: EpisodeKey
    path: Path


def episode_key(path: Path) -> EpisodeKey | None:
    info = parse_episode(path)
    if info is None:
        return None
    return EpisodeKey(display_title(path)["title"].casefold(), info.season, info.episode)


def is_watched(rec: WatchRecord) -> bool:
    return rec.completed or (rec.duration > 0 and rec.position / rec.duration >= WATCHED_AT)


def _state_key(path: Path) -> EpisodeKey | str:
    key = episode_key(path)
    return str(path) if key is None else key


class WatchStates:
    """Each episode's state is its newest meaningful row across every copy; a movie's is its file's."""

    def __init__(self, records: list[WatchRecord]) -> None:
        self._latest: dict[EpisodeKey | str, WatchRecord] = {}
        for rec in sorted(records, key=lambda r: (r.last_updated_at, r.id)):
            self._latest[_state_key(Path(rec.file_path))] = rec

    def of(self, path: Path) -> WatchRecord | None:
        return self._latest.get(_state_key(path))

    def is_watched(self, path: Path) -> bool:
        rec = self.of(path)
        return rec is not None and is_watched(rec)

    def resume_position(self, path: Path) -> float | None:
        rec = self.of(path)
        if rec is None or is_watched(rec) or rec.position <= 0:
            return None
        return rec.position


class Catalogue:
    """The watch folders' files grouped into shows, each in season/episode order, and movies."""

    def __init__(self, paths: list[Path]) -> None:
        self.shows: dict[str, list[Episode]] = {}
        self.movies: list[Path] = []
        for path in paths:
            key = episode_key(path)
            if key is None:
                self.movies.append(path)
            else:
                self.shows.setdefault(key.show, []).append(Episode(key, path))
        for eps in self.shows.values():
            eps.sort(key=lambda e: (e.key.order, str(e.path)))

    def show_of(self, path: Path) -> str | None:
        key = episode_key(path)
        if key is None or key.show not in self.shows:
            return None
        return key.show

    def next_after(self, path: Path) -> Path | None:
        """The next episode in the show's order; watched episodes are not skipped."""
        key = episode_key(path)
        if key is None or key.show not in self.shows:
            return None
        return next((e.path for e in self.shows[key.show] if e.key.order > key.order), None)

    def next_pick(self, show: str, states: WatchStates) -> tuple[Path | None, float | None]:
        """The episode to continue with and when the show was last active; the pick is None when there is none."""
        eps = self.shows[show]
        touched = [(rec, ep) for ep in eps if (rec := states.of(ep.path)) is not None]
        if not touched:
            return None, None
        rec, last = max(touched, key=lambda t: (t[0].last_updated_at, t[0].id))
        if not is_watched(rec):
            return self._copy(eps, last.key, Path(rec.file_path)), rec.last_updated_at
        for ep in eps:
            if ep.key.order > last.key.order and not states.is_watched(ep.path):
                return ep.path, rec.last_updated_at
        return None, rec.last_updated_at

    @staticmethod
    def _copy(eps: list[Episode], key: EpisodeKey, recorded: Path) -> Path:
        copies = [e.path for e in eps if e.key == key]
        return recorded if recorded in copies else copies[0]

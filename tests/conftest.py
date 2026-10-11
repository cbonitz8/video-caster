from __future__ import annotations

from pathlib import Path

import pytest

from video_caster.storage.history import HistoryStore


def make_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0")
    return path


@pytest.fixture
def history(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    yield store
    store.close()


@pytest.fixture
def watch_dir(tmp_path) -> Path:
    folder = tmp_path / "watch"
    make_video(folder / "Movie.mkv")
    return folder


@pytest.fixture
def video(watch_dir) -> Path:
    return watch_dir / "Movie.mkv"

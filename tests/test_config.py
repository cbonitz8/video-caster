from __future__ import annotations

import os
from pathlib import Path

import pytest

from video_caster.config import DEFAULT_WATCH_FOLDERS, Config, load_config, save_config


@pytest.fixture
def config_path(tmp_path) -> Path:
    return tmp_path / "video-caster" / "config.toml"


def test_paths_with_quotes_backslashes_and_tabs_round_trip(config_path, tmp_path):
    config = Config(
        watch_folders=[Path('/Volumes/stanley/Bob\'s "Best"'), Path("/tmp/a\\b"), Path("/tmp/a\tb")],
        recently_added_limit=7,
        history_db_path=tmp_path / 'his"tory.db',
    )
    save_config(config, config_path)
    assert load_config(config_path) == config


def test_an_empty_watch_folder_list_stays_empty(config_path):
    save_config(Config(watch_folders=[]), config_path)
    assert load_config(config_path).watch_folders == []


def test_a_missing_watch_folder_key_means_the_default(config_path):
    config_path.parent.mkdir(parents=True)
    config_path.write_text("recently_added_limit = 3\n")
    config = load_config(config_path)
    assert config.watch_folders == DEFAULT_WATCH_FOLDERS
    assert config.recently_added_limit == 3


def test_a_missing_file_means_the_defaults(config_path):
    assert load_config(config_path) == Config()


def test_a_failed_write_leaves_the_old_file_whole(config_path, monkeypatch):
    save_config(Config(recently_added_limit=4), config_path)
    before = config_path.read_bytes()

    def refuse(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError):
        save_config(Config(recently_added_limit=9), config_path)

    assert config_path.read_bytes() == before
    assert [p.name for p in config_path.parent.iterdir()] == ["config.toml"]

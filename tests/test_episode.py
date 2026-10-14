from __future__ import annotations

from pathlib import Path

from video_caster.storage.episode import find_next_episode, parse_episode, split_episode_name
from tests.conftest import make_video


def test_next_episode_ignores_appledouble_files(tmp_path):
    e6 = make_video(tmp_path / "Ted Lasso - S04E06 - Ice Cold.mkv")
    make_video(tmp_path / "._Ted Lasso - S04E07 - Yes & Baby.mkv")
    assert find_next_episode(e6) is None


def test_resolution_is_not_an_episode():
    assert parse_episode(Path("/m/Some.Movie.1920x1080.mkv")) is None


def test_1x03_still_parses():
    info = parse_episode(Path("/tv/Show.Name.1x03.Pilot.mkv"))
    assert (info.season, info.episode) == (1, 3)


def test_split_episode_name_from_file_name():
    assert split_episode_name(Path("/tv/Ted.Lasso.S04E05.Riches.1080p.mkv")) == (
        "Ted.Lasso.", ".Riches.1080p")


def test_split_episode_name_from_season_folder():
    assert split_episode_name(Path("/tv/Show/Season 1/03 - Pilot.mkv")) == ("", " - Pilot")


def test_split_episode_name_none_for_movies():
    assert split_episode_name(Path("/m/The.Matrix.1999.mkv")) is None

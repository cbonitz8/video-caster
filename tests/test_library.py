from __future__ import annotations

from video_caster import library
from video_caster.config import Config

from tests.conftest import make_video


async def test_has_file(history, video):
    assert await history.has_file(str(video)) is False
    await history.record_play(str(video), video.name, "dev", "Living Room", 100.0)
    assert await history.has_file(str(video)) is True


async def test_continue_watching_shape(history, video):
    wid = await history.record_play(str(video), video.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 30.0)
    assert await library.continue_watching(history) == [{
        "path": str(video),
        "name": "Movie.mkv",
        "position": 30.0,
        "duration": 100.0,
        "progress": 0.3,
    }]


async def test_up_next_suggests_next_episode(history, watch_dir):
    e1 = make_video(watch_dir / "Show" / "Season 1" / "Show.S01E01.mkv")
    e2 = make_video(watch_dir / "Show" / "Season 1" / "Show.S01E02.mkv")
    wid = await history.record_play(str(e1), e1.name, "dev", "Living Room", 100.0)
    await history.mark_completed(wid)
    assert await library.up_next(history) == [
        {"path": str(e2), "name": e2.name, "watched_name": e1.name},
    ]


async def test_up_next_skips_episode_already_in_history(history, watch_dir):
    e1 = make_video(watch_dir / "Show" / "Season 1" / "Show.S01E01.mkv")
    e2 = make_video(watch_dir / "Show" / "Season 1" / "Show.S01E02.mkv")
    for ep in (e1, e2):
        wid = await history.record_play(str(ep), ep.name, "dev", "Living Room", 100.0)
        await history.mark_completed(wid)
    assert await library.up_next(history) == []


async def test_newly_added_skips_missing_folder(watch_dir, tmp_path):
    config = Config(watch_folders=[tmp_path / "unplugged", watch_dir], recently_added_limit=20)
    items = await library.newly_added(config)
    assert [i["name"] for i in items] == ["Movie.mkv"]
    assert items[0]["path"] == str(watch_dir / "Movie.mkv")
    assert items[0]["size"] == 1

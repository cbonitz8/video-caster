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
        "title": "Movie",
        "subtitle": None,
        "position": 30.0,
        "duration": 100.0,
        "progress": 0.3,
    }]


async def test_up_next_suggests_next_episode(history, watch_dir):
    e1 = make_video(watch_dir / "Show" / "Season 1" / "Show.S01E01.mkv")
    e2 = make_video(watch_dir / "Show" / "Season 1" / "Show.S01E02.mkv")
    wid = await history.record_play(str(e1), e1.name, "dev", "Living Room", 100.0)
    await history.mark_completed(wid)
    assert await library.up_next(history) == [{
        "path": str(e2),
        "name": e2.name,
        "title": "Show",
        "subtitle": "S01E02",
        "position": None,
        "watched_name": e1.name,
        "watched": {"title": "Show", "subtitle": "S01E01"},
    }]


async def test_up_next_skips_episode_already_in_history(history, watch_dir):
    e1 = make_video(watch_dir / "Show" / "Season 1" / "Show.S01E01.mkv")
    e2 = make_video(watch_dir / "Show" / "Season 1" / "Show.S01E02.mkv")
    for ep in (e1, e2):
        wid = await history.record_play(str(ep), ep.name, "dev", "Living Room", 100.0)
        await history.mark_completed(wid)
    assert await library.up_next(history) == []


async def test_newly_added_skips_missing_folder(history, watch_dir, tmp_path):
    config = Config(watch_folders=[tmp_path / "unplugged", watch_dir], recently_added_limit=20)
    items = await library.newly_added(config, history)
    assert [i["name"] for i in items] == ["Movie.mkv"]
    assert items[0]["path"] == str(watch_dir / "Movie.mkv")
    assert items[0]["size"] == 1


async def test_positions_for_only_in_progress(history, watch_dir):
    playing = make_video(watch_dir / "a.mkv")
    finished = make_video(watch_dir / "b.mkv")
    unstarted = make_video(watch_dir / "c.mkv")
    wid = await history.record_play(str(playing), playing.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 30.0)
    wid = await history.record_play(str(finished), finished.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 95.0)
    await history.mark_completed(wid)
    await history.record_play(str(unstarted), unstarted.name, "dev", "Living Room", 100.0)
    paths = [str(p) for p in (playing, finished, unstarted, watch_dir / "never.mkv")]
    assert await history.positions_for(paths) == {str(playing): 30.0}


async def test_positions_for_empty_list(history):
    assert await history.positions_for([]) == {}


async def test_positions_for_more_paths_than_sqlite_parameters(history, watch_dir):
    last = make_video(watch_dir / "last.mkv")
    wid = await history.record_play(str(last), last.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 7.0)
    paths = [str(watch_dir / f"f{i}.mkv") for i in range(1200)] + [str(last)]
    assert await history.positions_for(paths) == {str(last): 7.0}


async def test_newly_added_rows_have_titles_and_positions(history, watch_dir):
    ep = make_video(watch_dir / "Show.S01E02.Second.mkv")
    wid = await history.record_play(str(ep), ep.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 12.0)
    config = Config(watch_folders=[watch_dir], recently_added_limit=20)
    rows = {r["name"]: r for r in await library.newly_added(config, history)}
    assert rows["Show.S01E02.Second.mkv"]["title"] == "Show"
    assert rows["Show.S01E02.Second.mkv"]["subtitle"] == "S01E02 · Second"
    assert rows["Show.S01E02.Second.mkv"]["position"] == 12.0
    assert rows["Movie.mkv"]["position"] is None

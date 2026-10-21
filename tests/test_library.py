from __future__ import annotations

import os

from video_caster import library
from video_caster.config import Config

from tests.conftest import make_video


def at(history, wid, when):
    conn = history._get_conn()
    conn.execute("UPDATE watch_history SET last_updated_at = ? WHERE id = ?", (when, wid))
    conn.commit()


async def test_has_file(history, video):
    assert await history.has_file(str(video)) is False
    await history.record_play(str(video), video.name, "dev", "Living Room", 100.0)
    assert await history.has_file(str(video)) is True


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


async def test_latest_meaningful_prefers_rewatch_over_completed(history, video):
    wid = await history.record_play(str(video), video.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 98.0)
    await history.mark_completed(wid)
    rewatch = await history.record_play(str(video), video.name, "dev", "Living Room", 100.0)
    await history.force_update_position(rewatch, 40.0)
    at(history, wid, 1.0)
    at(history, rewatch, 2.0)
    rec = (await history.latest_meaningful([str(video)]))[str(video)]
    assert (rec.id, rec.position, rec.completed) == (rewatch, 40.0, False)


async def test_latest_meaningful_ignores_position_zero_rows(history, video):
    wid = await history.record_play(str(video), video.name, "dev", "Living Room", 100.0)
    await history.mark_completed(wid)
    newer = await history.record_play(str(video), video.name, "dev", "Living Room", 100.0)
    at(history, wid, 1.0)
    at(history, newer, 2.0)
    rec = (await history.latest_meaningful([str(video)]))[str(video)]
    assert rec.id == wid and rec.completed is True


async def test_latest_meaningful_omits_untouched_and_unlisted(history, watch_dir):
    a = make_video(watch_dir / "a.mkv")
    await history.record_play(str(a), a.name, "dev", "Living Room", 100.0)
    assert await history.latest_meaningful([str(a), str(watch_dir / "never.mkv")]) == {}


async def test_latest_meaningful_more_paths_than_sqlite_parameters(history, watch_dir):
    last = make_video(watch_dir / "last.mkv")
    wid = await history.record_play(str(last), last.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 7.0)
    paths = [str(watch_dir / f"f{i}.mkv") for i in range(1200)] + [str(last)]
    assert list(await history.latest_meaningful(paths)) == [str(last)]


async def play(history, path, position, *, completed=False, when=None, duration=100.0):
    wid = await history.record_play(str(path), path.name, "dev", "Living Room", duration)
    if position:
        await history.force_update_position(wid, position)
    if completed:
        await history.mark_completed(wid)
    if when is not None:
        at(history, wid, when)
    return wid


def cfg(*folders):
    return Config(watch_folders=list(folders), recently_added_limit=20)


async def build(history, tmp_path, *folders):
    return await library.build_library(cfg(*folders), history, tmp_path / "posters")


def episodes(watch_dir, *codes, show="Show"):
    return [make_video(watch_dir / show / f"{show}.{code}.mkv") for code in codes]


async def test_sections(history, watch_dir, tmp_path):
    lib = await build(history, tmp_path, watch_dir)
    assert set(lib) == {"continue", "shows", "movies", "newly_added"}


async def test_show_groups_across_folders_and_case(history, watch_dir, tmp_path):
    e2 = make_video(watch_dir / "A" / "Show.S01E02.mkv")
    e1 = make_video(watch_dir / "B" / "show.S01E01.mkv")
    lib = await build(history, tmp_path, watch_dir)
    assert len(lib["shows"]) == 1
    show = lib["shows"][0]
    assert (show["key"], show["episode_count"]) == ("show", 2)
    assert [s["season"] for s in show["seasons"]] == [1]
    assert [e["path"] for e in show["seasons"][0]["episodes"]] == [str(e1), str(e2)]
    assert [(e["season"], e["episode"]) for e in show["seasons"][0]["episodes"]] == [(1, 1), (1, 2)]


async def test_movie_is_non_episode(history, watch_dir, tmp_path):
    episodes(watch_dir, "S01E01")
    lib = await build(history, tmp_path, watch_dir)
    assert [m["title"] for m in lib["movies"]] == ["Movie"]
    assert [s["title"] for s in lib["shows"]] == ["Show"]


async def test_continue_in_progress_episode(history, watch_dir, tmp_path):
    e1, _ = episodes(watch_dir, "S01E01", "S01E02")
    await play(history, e1, 30.0)
    tile = (await build(history, tmp_path, watch_dir))["continue"][0]
    assert (tile["path"], tile["position"], tile["duration"], tile["watched"]) == (str(e1), 30.0, 100.0, False)
    assert tile["title"] == "Show"


async def test_continue_moves_past_watched_to_next_unwatched(history, watch_dir, tmp_path):
    e1, e2, e3 = episodes(watch_dir, "S01E01", "S01E02", "S01E03")
    await play(history, e2, 95.0, completed=True, when=1.0)
    await play(history, e1, 95.0, completed=True, when=2.0)
    lib = await build(history, tmp_path, watch_dir)
    assert [t["path"] for t in lib["continue"]] == [str(e3)]


async def test_continue_rewatch_counts_as_in_progress(history, watch_dir, tmp_path):
    e1, _ = episodes(watch_dir, "S01E01", "S01E02")
    await play(history, e1, 95.0, completed=True, when=1.0)
    await play(history, e1, 40.0, when=2.0)
    tile = (await build(history, tmp_path, watch_dir))["continue"][0]
    assert (tile["path"], tile["position"]) == (str(e1), 40.0)


async def test_continue_ignores_position_zero_rows(history, watch_dir, tmp_path):
    e1, e2 = episodes(watch_dir, "S01E01", "S01E02")
    await play(history, e1, 95.0, completed=True, when=1.0)
    await play(history, e2, 0.0, when=2.0)
    tile = (await build(history, tmp_path, watch_dir))["continue"][0]
    assert (tile["path"], tile["position"]) == (str(e2), None)


async def test_show_leaves_continue_when_nothing_after_is_unwatched(history, watch_dir, tmp_path):
    e1, e2 = episodes(watch_dir, "S01E01", "S01E02")
    await play(history, e1, 95.0, completed=True, when=1.0)
    await play(history, e2, 95.0, completed=True, when=2.0)
    lib = await build(history, tmp_path, watch_dir)
    assert lib["continue"] == []
    assert lib["shows"][0]["up_next"] is None


async def test_up_next_falls_back_to_first_unwatched(history, watch_dir, tmp_path):
    e1, e3 = episodes(watch_dir, "S01E01", "S01E03")
    await play(history, e3, 95.0, completed=True)
    lib = await build(history, tmp_path, watch_dir)
    assert lib["continue"] == []
    assert lib["shows"][0]["up_next"]["path"] == str(e1)


async def test_up_next_first_episode_without_history(history, watch_dir, tmp_path):
    e1, _ = episodes(watch_dir, "S01E01", "S01E02")
    lib = await build(history, tmp_path, watch_dir)
    assert lib["shows"][0]["up_next"]["path"] == str(e1)


async def test_continue_newest_activity_first(history, watch_dir, video, tmp_path):
    (e1,) = episodes(watch_dir, "S01E01", show="A")
    await play(history, e1, 30.0, when=1.0)
    await play(history, video, 30.0, when=2.0)
    lib = await build(history, tmp_path, watch_dir)
    assert [t["path"] for t in lib["continue"]] == [str(video), str(e1)]


async def test_continue_skips_history_outside_watch_folders(history, watch_dir, tmp_path):
    clip = make_video(tmp_path / "elsewhere" / "Clip.mkv")
    await play(history, clip, 30.0)
    assert (await build(history, tmp_path, watch_dir))["continue"] == []


async def test_unplugged_watch_folder_still_loads(history, watch_dir, video, tmp_path):
    lib = await build(history, tmp_path, tmp_path / "unplugged", watch_dir)
    assert [m["path"] for m in lib["movies"]] == [str(video)]


async def test_duration_zero_never_watched(history, watch_dir, video, tmp_path):
    await play(history, video, 50.0, duration=0.0)
    movie = (await build(history, tmp_path, watch_dir))["movies"][0]
    assert (movie["watched"], movie["position"]) == (False, 50.0)


async def test_art_attached(history, watch_dir, tmp_path):
    episodes(watch_dir, "S01E01")
    art = tmp_path / "posters"
    art.mkdir()
    (art / "show.jpg").write_bytes(b"x")
    (art / "movie-wide.jpg").write_bytes(b"x")
    lib = await build(history, tmp_path, watch_dir)
    show = lib["shows"][0]
    assert show["poster"].startswith("/posters/show.jpg?v=") and show["wide"] is None
    assert show["slug"] == "show"
    movie = next(r for r in lib["newly_added"] if r["title"] == "Movie")
    assert movie["wide"].startswith("/posters/movie-wide.jpg?v=") and movie["poster"] is None


async def test_newly_added_rows(history, watch_dir, video, tmp_path):
    (e1,) = episodes(watch_dir, "S01E01")
    os.utime(video, (1, 1))
    await play(history, e1, 12.0)
    rows = (await build(history, tmp_path, watch_dir))["newly_added"]
    assert [r["path"] for r in rows] == [str(e1), str(video)]
    assert rows[0]["mtime_ago"]
    assert (rows[0]["position"], rows[0]["duration"], rows[0]["watched"]) == (12.0, 100.0, False)
    assert rows[1]["position"] is None

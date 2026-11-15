from __future__ import annotations


async def play(history, path, duration=100.0):
    return await history.record_play(str(path), path.name, "dev", "Living Room", duration)


def positions(records):
    return [(r.file_path, r.position, r.completed) for r in records]


async def test_has_file(history, video):
    assert await history.has_file(str(video)) is False
    await play(history, video)
    assert await history.has_file(str(video)) is True


async def test_record_play_reuses_the_unfinished_row(history, video):
    first = await play(history, video)
    await history.force_update_position(first, 30.0)
    assert await play(history, video) == first


async def test_record_play_after_completion_starts_a_new_row(history, video):
    first = await play(history, video)
    await history.mark_completed(first)
    assert await play(history, video) != first


async def test_meaningful_records_skip_rows_left_at_zero(history, watch_dir):
    started = watch_dir / "a.mkv"
    finished = watch_dir / "b.mkv"
    untouched = watch_dir / "c.mkv"
    wid = await play(history, started)
    await history.force_update_position(wid, 30.0)
    wid = await play(history, finished)
    await history.mark_completed(wid)
    await play(history, untouched)
    assert positions(await history.meaningful_records()) == [
        (str(started), 30.0, False), (str(finished), 0.0, True)]


async def test_meaningful_records_oldest_first(history, video):
    wid = await play(history, video)
    await history.force_update_position(wid, 98.0)
    await history.mark_completed(wid)
    rewatch = await play(history, video)
    await history.force_update_position(rewatch, 40.0)
    assert positions(await history.meaningful_records()) == [
        (str(video), 98.0, True), (str(video), 40.0, False)]


async def test_update_duration_only_fills_an_unknown_duration(history, video):
    wid = await play(history, video, duration=0.0)
    await history.update_duration(wid, 50.0)
    await history.update_duration(wid, 70.0)
    await history.force_update_position(wid, 1.0)
    assert (await history.meaningful_records())[0].duration == 50.0


async def test_position_throttle_is_per_row(history, watch_dir):
    a = await play(history, watch_dir / "a.mkv")
    b = await play(history, watch_dir / "b.mkv")
    await history.update_position(a, 10.0)
    await history.update_position(b, 20.0)
    await history.update_position(a, 11.0)
    assert [r.position for r in await history.meaningful_records()] == [10.0, 20.0]

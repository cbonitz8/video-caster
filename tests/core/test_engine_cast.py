from __future__ import annotations

import asyncio
import dataclasses

import pytest

from video_caster.casting.base import PairingFailed, PlaybackStatus
from video_caster.core.errors import Conflict, NotFound
from tests.conftest import BEDROOM, LIVING_ROOM, drain, make_video


async def test_scan_lists_devices_and_publishes(engine):
    queue = engine.events.subscribe()
    await engine.scan_devices()
    state = engine.state()
    assert [d["id"] for d in state["devices"]] == [LIVING_ROOM.id, BEDROOM.id]
    assert state["scan"] == {"running": False, "warning": ""}
    events = drain(queue)
    assert [e["type"] for e in events] == ["devices", "devices"]
    assert events[0]["data"]["scan"]["running"] is True


async def test_scan_warns_when_multicast_blocked(make_engine):
    engine = make_engine(devices=(), multicast_blocked=True)
    await engine.scan_devices()
    assert "Local Network" in engine.state()["scan"]["warning"]


async def test_scan_failure_publishes_error(make_engine):
    engine = make_engine()

    async def broken_scan(timeout):
        raise OSError("no route to host")

    engine._scan = broken_scan
    queue = engine.events.subscribe()
    await engine.scan_devices()
    errors = [e for e in drain(queue) if e["type"] == "error"]
    assert errors == [{"type": "error", "data": {
        "message": "Device scan failed: no route to host", "source": "scan"}}]
    assert engine.state()["scan"]["running"] is False


async def test_cast_waits_for_device_then_casts_on_select(engine, orchestrator, video):
    await engine.scan_devices()
    assert engine.request_cast(video, resume=False) == {
        "status": "waiting_for_device", "device": None}
    assert engine.state()["pending"] == {
        "path": str(video), "title": "Movie", "subtitle": None, "resume": False}

    engine.select_device(LIVING_ROOM.id)
    await engine.cast_task

    assert ("cast_file", video, LIVING_ROOM.id) in orchestrator.calls
    state = engine.state()
    assert state["pending"] is None
    assert state["selected_device"] == LIVING_ROOM.id
    assert state["current"] == {"path": str(video), "title": "Movie", "subtitle": None, "next": None}


async def test_cast_records_history_and_announces(engine, history, video):
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    queue = engine.events.subscribe()
    assert engine.request_cast(video, resume=False) == {
        "status": "casting", "device": "Living Room"}
    await engine.cast_task
    assert await history.has_file(str(video))
    assert {"type": "library_changed", "data": None} in drain(queue)


async def test_resume_seeks_to_saved_position(engine, orchestrator, history, video):
    wid = await history.record_play(str(video), video.name, "x", "x", 100.0)
    await history.force_update_position(wid, 42.0)
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    engine.request_cast(video, resume=True)
    await engine.cast_task
    assert ("seek", 42.0) in orchestrator.calls


async def test_failed_cast_publishes_error(engine, orchestrator, video):
    orchestrator.cast_error = RuntimeError("LOAD_FAILED")
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    queue = engine.events.subscribe()
    engine.request_cast(video, resume=False)
    await engine.cast_task
    errors = [e for e in drain(queue) if e["type"] == "error"]
    assert errors == [{"type": "error", "data": {
        "message": "Cast failed: LOAD_FAILED", "source": "cast"}}]
    assert engine.state()["current"] is None


async def cast_errors(engine, video) -> list[dict]:
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    queue = engine.events.subscribe()
    engine.request_cast(video, resume=False)
    await engine.cast_task
    return [e["data"] for e in drain(queue) if e["type"] == "error"]


async def test_pairing_failure_reaches_the_phone(engine, orchestrator, video):
    orchestrator.cast_error = PairingFailed("Pairing with Den failed: bad pin")
    assert await cast_errors(engine, video) == [
        {"message": "Cast failed: Pairing with Den failed: bad pin", "source": "cast"}]


async def test_pin_timeout_reaches_the_phone(engine, orchestrator, video):
    orchestrator.asks_pin = True
    assert await cast_errors(engine, video) == [
        {"message": "Cast failed: No PIN entered for Living Room within 0s", "source": "cast"}]
    assert engine.state()["pin_request"] is None


async def test_second_cast_cancels_first(engine, orchestrator, watch_dir):
    first_file = watch_dir / "Movie.mkv"
    second_file = make_video(watch_dir / "Other.mkv")
    orchestrator.cast_gate = asyncio.Event()
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)

    engine.request_cast(first_file, resume=False)
    first = engine.cast_task
    await asyncio.sleep(0)
    engine.request_cast(second_file, resume=False)
    second = engine.cast_task
    orchestrator.cast_gate.set()
    await second
    await asyncio.gather(first, return_exceptions=True)

    assert first.cancelled()
    assert engine.state()["current"]["path"] == str(second_file)


def test_select_unknown_device_raises(engine):
    with pytest.raises(NotFound):
        engine.select_device("chromecast:10.0.0.1:8009")


async def test_library_has_shelf_sections(engine):
    assert set(await engine.library()) == {"continue", "shows", "movies", "newly_added"}


def last_current(events: list[dict]) -> dict:
    return [e["data"] for e in events if e["type"] == "current"][-1]


async def test_current_event_tracks_pending_cast_and_stop(engine, video):
    await engine.scan_devices()
    queue = engine.events.subscribe()
    engine.request_cast(video, resume=False)
    assert last_current(drain(queue)) == {"current": None, "casting": None, "pending": {
        "path": str(video), "title": "Movie", "subtitle": None, "resume": False}}
    engine.select_device(LIVING_ROOM.id)
    await engine.cast_task
    assert last_current(drain(queue)) == {"pending": None, "casting": None, "current": {
        "path": str(video), "title": "Movie", "subtitle": None, "next": None}}
    await engine.stop()
    assert last_current(drain(queue)) == {"current": None, "pending": None, "casting": None}


async def test_stop_announces_cleared_pending(engine, video):
    await engine.scan_devices()
    engine.request_cast(video, resume=False)
    queue = engine.events.subscribe()
    await engine.stop()
    assert last_current(drain(queue)) == {"current": None, "pending": None, "casting": None}


async def test_current_carries_next_episode(engine, watch_dir):
    e1 = make_video(watch_dir / "Show.S01E01.mkv")
    e2 = make_video(watch_dir / "Show.S01E02.Second.mkv")
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    engine.request_cast(e1, resume=False)
    await engine.cast_task
    assert engine.state()["current"]["next"] == {
        "path": str(e2), "title": "Show", "subtitle": "S01E02 · Second"}
    assert engine.next_episode() == e2


async def cast_and_finish(engine, orchestrator, path) -> None:
    await cast(engine, path)
    orchestrator.status = PlaybackStatus(state="playing", current_time=95.0, duration=100.0)
    await engine.tick()


async def cast(engine, path) -> None:
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    engine.request_cast(path, resume=False)
    await engine.cast_task


async def test_next_agrees_with_up_next_while_watching_forward(engine, orchestrator, watch_dir):
    season = watch_dir / "Show" / "Season 1"
    eps = [make_video(season / f"Show - S01E0{n} - Part {n}.mkv") for n in (1, 2, 4)]
    eps.append(make_video(watch_dir / "elsewhere" / "Show.S02E01.mkv"))
    for ep, after in zip(eps, eps[1:]):
        await cast_and_finish(engine, orchestrator, ep)
        up_next = (await engine.library())["shows"][0]["up_next"]["path"]
        assert str(engine.next_episode()) == up_next == str(after)


async def test_next_for_a_file_outside_the_watch_folders_comes_from_the_library(engine, watch_dir, tmp_path):
    outside = make_video(tmp_path / "Movies" / "Ted.Lasso.S04E04.1080p.HEVC.x265-MeGusta[EZTVx.to].mkv")
    e5 = make_video(watch_dir / "Ted Lasso" / "Season 4" / "Ted Lasso - S04E05 - Riches of Embarrassment.mkv")
    await cast(engine, outside)
    assert engine.next_episode() == e5


async def test_unmounted_watch_folder_means_no_next_not_a_failed_cast(make_engine, orchestrator, tmp_path, caplog):
    engine = make_engine(watch_folders=[tmp_path / "stanley"])
    e1 = make_video(tmp_path / "Show.S01E01.mkv")
    make_video(tmp_path / "Show.S01E02.mkv")
    await cast(engine, e1)
    assert engine.state()["current"]["path"] == str(e1)
    assert engine.state()["current"]["next"] is None
    assert "Watch folder does not exist" in caplog.text


async def test_failed_scan_means_no_next_not_a_failed_cast(engine, watch_dir, monkeypatch, caplog):
    async def broken_scan(*args, **kwargs):
        raise OSError("Host is down")

    monkeypatch.setattr("video_caster.core.engine.scan_watch_folders", broken_scan)
    e1 = make_video(watch_dir / "Show.S01E01.mkv")
    make_video(watch_dir / "Show.S01E02.mkv")
    await cast(engine, e1)
    assert engine.state()["current"]["path"] == str(e1)
    assert engine.state()["current"]["next"] is None
    assert "Host is down" in caplog.text


async def test_resume_uses_the_episode_position_from_another_copy(engine, orchestrator, history, watch_dir, tmp_path):
    old = tmp_path / "gone" / "Show.S01E01.mkv"
    new = make_video(watch_dir / "Show" / "Season 1" / "Show - S01E01 - Pilot.mkv")
    wid = await history.record_play(str(old), old.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 42.0)
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    engine.request_cast(new, resume=True)
    await engine.cast_task
    assert ("seek", 42.0) in orchestrator.calls


def test_next_episode_needs_current(engine):
    with pytest.raises(Conflict, match="Nothing is playing"):
        engine.next_episode()


async def test_next_episode_needs_a_next(engine, video):
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    engine.request_cast(video, resume=False)
    await engine.cast_task
    with pytest.raises(Conflict, match="No next episode"):
        engine.next_episode()


async def test_casting_names_the_file_while_its_cast_is_in_flight(engine, orchestrator, video):
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    orchestrator.cast_gate = asyncio.Event()
    queue = engine.events.subscribe()
    engine.request_cast(video, resume=False)
    await asyncio.sleep(0)
    assert engine.state()["casting"] == {"path": str(video), "title": "Movie", "subtitle": None}
    assert last_current(drain(queue))["casting"]["path"] == str(video)
    orchestrator.cast_gate.set()
    await engine.cast_task
    assert engine.state()["casting"] is None
    assert last_current(drain(queue))["casting"] is None


async def test_failed_cast_clears_casting(engine, orchestrator, video):
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    orchestrator.cast_error = RuntimeError("TV said no")
    queue = engine.events.subscribe()
    engine.request_cast(video, resume=False)
    await engine.cast_task
    assert last_current(drain(queue)) == {"current": None, "pending": None, "casting": None}


async def test_stop_mid_cast_clears_casting(engine, orchestrator, video):
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    orchestrator.cast_gate = asyncio.Event()
    engine.request_cast(video, resume=False)
    await asyncio.sleep(0)
    queue = engine.events.subscribe()
    await engine.stop()
    assert engine.state()["casting"] is None
    assert last_current(drain(queue))["casting"] is None


async def test_replaced_cast_keeps_the_new_casting(engine, orchestrator, video, watch_dir):
    other = make_video(watch_dir / "Other.mkv")
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    orchestrator.cast_gate = asyncio.Event()
    engine.request_cast(video, resume=False)
    await asyncio.sleep(0)
    engine.request_cast(other, resume=False)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert engine.state()["casting"]["path"] == str(other)
    orchestrator.cast_gate.set()
    await engine.cast_task


async def test_rescan_refreshes_the_selected_device(make_engine, orchestrator, video):
    moved = dataclasses.replace(LIVING_ROOM, address="192.168.10.99")
    engine = make_engine(devices=(LIVING_ROOM,))
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)

    async def rescan(timeout):
        return [moved]

    engine._scan = rescan
    await engine.scan_devices()

    assert engine.selected_device is moved
    engine.request_cast(video, resume=False)
    await engine.cast_task
    assert orchestrator.devices[-1] is moved


async def test_rescan_keeps_the_selected_device_when_it_is_missing(make_engine):
    engine = make_engine(devices=(LIVING_ROOM,))
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)

    async def empty_scan(timeout):
        return []

    engine._scan = empty_scan
    await engine.scan_devices()

    assert engine.selected_device is LIVING_ROOM
    assert engine.state()["selected_device"] == LIVING_ROOM.id

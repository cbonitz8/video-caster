from __future__ import annotations

import asyncio

import pytest

from video_caster.core.errors import NotFound
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
    assert engine.state()["pending"] == {"path": str(video), "resume": False}

    engine.select_device(LIVING_ROOM.id)
    await engine.cast_task

    assert ("cast_file", video, LIVING_ROOM.id) in orchestrator.calls
    state = engine.state()
    assert state["pending"] is None
    assert state["selected_device"] == LIVING_ROOM.id
    assert state["current"] == {"path": str(video), "title": "Movie"}


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


async def test_library_has_three_sections(engine):
    assert set(await engine.library()) == {"continue_watching", "up_next", "newly_added"}

from __future__ import annotations

import asyncio

import pytest

from video_caster.casting.base import DeviceRequestFailed, PlaybackStatus
from video_caster.core.errors import BadRequest, DeviceError
from tests.conftest import saved_position, LIVING_ROOM, drain, make_video


async def start_casting(engine, video) -> None:
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    engine.request_cast(video, resume=False)
    await engine.cast_task


async def test_tick_publishes_status_with_title_fallback(engine, orchestrator, video):
    await start_casting(engine, video)
    queue = engine.events.subscribe()
    orchestrator.status = PlaybackStatus(state="playing", current_time=10.0, duration=100.0)
    await engine.tick()
    assert drain(queue)[0] == {"type": "status", "data": {
        "state": "playing", "current_time": 10.0, "duration": 100.0,
        "volume": 1.0, "title": "Movie"}}


async def test_tick_skips_unchanged_paused_status(engine, orchestrator):
    orchestrator.status = PlaybackStatus(state="paused", current_time=5.0, duration=100.0)
    queue = engine.events.subscribe()
    await engine.tick()
    await engine.tick()
    assert [e["type"] for e in drain(queue)] == ["status"]


async def test_tick_saves_position_midway(engine, orchestrator, history, video):
    await start_casting(engine, video)
    orchestrator.status = PlaybackStatus(state="playing", current_time=30.0, duration=100.0)
    await engine.tick()
    assert await saved_position(history, video) == 30.0


async def test_tick_marks_completed_at_ninety_percent(engine, orchestrator, history, video):
    await start_casting(engine, video)
    queue = engine.events.subscribe()
    orchestrator.status = PlaybackStatus(state="playing", current_time=95.0, duration=100.0)
    await engine.tick()
    assert await saved_position(history, video) is None
    assert [r.completed for r in await history.meaningful_records()] == [True]
    assert {"type": "library_changed", "data": None} in drain(queue)


async def test_tick_error_published_once_per_failure(engine, orchestrator):
    queue = engine.events.subscribe()
    orchestrator.status_error = RuntimeError("socket closed")
    await engine.tick()
    await engine.tick()
    orchestrator.status_error = None
    await engine.tick()
    orchestrator.status_error = RuntimeError("socket closed")
    await engine.tick()
    errors = [e["data"] for e in drain(queue) if e["type"] == "error"]
    assert errors == [
        {"message": "Status update failed: socket closed", "source": "status"},
        {"message": "Status update failed: socket closed", "source": "status"},
    ]


async def test_seek_offset_clamps_to_duration(engine, orchestrator):
    orchestrator.status = PlaybackStatus(state="playing", current_time=90.0, duration=100.0)
    await engine.seek(offset=60.0)
    assert orchestrator.calls[-1] == ("seek", 100.0)
    await engine.seek(offset=-200.0)
    assert orchestrator.calls[-1] == ("seek", 0.0)


async def test_seek_absolute(engine, orchestrator):
    await engine.seek(position=12.5)
    assert orchestrator.calls[-1] == ("seek", 12.5)


@pytest.mark.parametrize("kwargs", [{}, {"position": 1.0, "offset": 1.0}])
async def test_seek_needs_exactly_one_argument(engine, kwargs):
    with pytest.raises(BadRequest):
        await engine.seek(**kwargs)


async def test_volume_is_clamped_and_stored(engine, orchestrator):
    await engine.set_volume(1.7)
    assert orchestrator.calls[-1] == ("set_volume", 1.0)
    assert engine.volume == 1.0


async def test_stop_saves_position(engine, orchestrator, history, video):
    await start_casting(engine, video)
    orchestrator.status = PlaybackStatus(state="playing", current_time=33.0, duration=100.0)
    await engine.stop()
    assert await saved_position(history, video) == 33.0
    assert ("stop_playback",) in orchestrator.calls
    assert engine.state()["current"] is None


async def test_stop_still_stops_when_status_fails(engine, orchestrator, video):
    await start_casting(engine, video)
    orchestrator.status_error = RuntimeError("gone")
    queue = engine.events.subscribe()
    await engine.stop()
    assert ("stop_playback",) in orchestrator.calls
    errors = [e["data"] for e in drain(queue) if e["type"] == "error"]
    assert errors == [{"message": "Couldn't save position: gone", "source": "stop"}]


async def test_device_timeout_propagates(engine, orchestrator):
    orchestrator.command_error = TimeoutError("Living Room didn't answer pause")
    with pytest.raises(TimeoutError):
        await engine.toggle_pause()


@pytest.mark.parametrize("command", [
    lambda engine: engine.toggle_pause(),
    lambda engine: engine.seek(position=12.0),
    lambda engine: engine.set_volume(0.5),
])
async def test_a_request_the_device_refused_is_a_device_error(engine, orchestrator, command):
    orchestrator.command_error = DeviceRequestFailed("Living Room didn't pause: Failed to execute play")
    with pytest.raises(DeviceError, match="Living Room didn't pause"):
        await command(engine)


async def test_stop_cancels_a_cast_still_loading(engine, orchestrator, video):
    orchestrator.cast_gate = asyncio.Event()
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    engine.request_cast(video, resume=False)
    await asyncio.sleep(0)
    await engine.stop()
    orchestrator.cast_gate.set()
    await asyncio.sleep(0)
    assert engine.cast_task.cancelled()
    assert engine.state()["current"] is None


async def test_stop_forgets_a_waiting_file(engine, video):
    engine.request_cast(video, resume=False)
    await engine.stop()
    assert engine.state()["pending"] is None



async def test_failed_replacement_clears_current_and_saves_old_position(
        engine, orchestrator, history, watch_dir, video):
    await start_casting(engine, video)
    orchestrator.status = PlaybackStatus(state="playing", current_time=40.0, duration=100.0)
    other = make_video(watch_dir / "Other.mkv")
    orchestrator.cast_error = RuntimeError("LOAD_FAILED")
    engine.request_cast(other, resume=False)
    await engine.cast_task
    assert engine.state()["current"] is None
    assert await saved_position(history, video) == 40.0


async def test_a_stop_the_device_refused_is_a_device_error_after_saving(
    engine, orchestrator, history, video
):
    await start_casting(engine, video)
    orchestrator.status = PlaybackStatus(state="playing", current_time=33.0, duration=100.0)
    orchestrator.command_error = DeviceRequestFailed("Living Room didn't stop: 701")
    queue = engine.events.subscribe()

    with pytest.raises(DeviceError, match="Living Room didn't stop"):
        await engine.stop()

    assert await saved_position(history, video) == 33.0
    assert engine.state()["current"] is None
    assert "library_changed" in [e["type"] for e in drain(queue)]


async def test_a_stop_timeout_stays_a_timeout(engine, orchestrator, video):
    await start_casting(engine, video)
    orchestrator.command_error = TimeoutError("Living Room didn't answer stop")
    with pytest.raises(TimeoutError):
        await engine.stop()

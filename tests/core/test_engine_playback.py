from __future__ import annotations

import pytest
from pychromecast.error import RequestTimeout

from video_caster.casting.base import PlaybackStatus
from video_caster.core.errors import BadRequest
from tests.conftest import LIVING_ROOM, drain


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
    assert await history.get_saved_position(str(video)) == 30.0


async def test_tick_marks_completed_at_ninety_percent(engine, orchestrator, history, video):
    await start_casting(engine, video)
    queue = engine.events.subscribe()
    orchestrator.status = PlaybackStatus(state="playing", current_time=95.0, duration=100.0)
    await engine.tick()
    assert await history.get_saved_position(str(video)) == 0.0  # completed rows don't resume
    completed = await history.get_completed_or_nearly()
    assert completed[0].file_path == str(video)
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
    assert await history.get_saved_position(str(video)) == 33.0
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
    orchestrator.command_error = RequestTimeout("play", 10.0)
    with pytest.raises(RequestTimeout):
        await engine.toggle_pause()

from __future__ import annotations

import asyncio

import pytest

from video_caster.casting.base import PlaybackStatus
from video_caster.core.errors import BadRequest, Conflict
from tests.conftest import LIVING_ROOM, drain


async def test_pin_round_trip(engine):
    queue = engine.events.subscribe()
    waiter = asyncio.create_task(engine.pin_callback("Bedroom TV", "AirPlay"))
    await asyncio.sleep(0)
    assert engine.state()["pin_request"] == {"device_name": "Bedroom TV", "protocol": "AirPlay"}
    engine.submit_pin("1234")
    assert await waiter == "1234"
    assert [e["type"] for e in drain(queue)] == ["pin_required", "pin_resolved"]
    assert engine.state()["pin_request"] is None


async def test_pin_times_out(engine):
    with pytest.raises(TimeoutError, match="No PIN entered for Bedroom TV"):
        await engine.pin_callback("Bedroom TV", "AirPlay")
    assert engine.state()["pin_request"] is None


def test_submit_pin_without_request(engine):
    with pytest.raises(Conflict):
        engine.submit_pin("1234")


async def test_start_and_shutdown(engine, orchestrator, video):
    await engine.start()
    assert orchestrator.pin_callback == engine.pin_callback
    await asyncio.sleep(0.05)  # first scan and a few ticks
    assert [d["id"] for d in engine.state()["devices"]][0] == LIVING_ROOM.id

    engine.select_device(LIVING_ROOM.id)
    engine.request_cast(video, resume=False)
    await engine.cast_task
    orchestrator.status = PlaybackStatus(state="playing", current_time=21.0, duration=100.0)

    await engine.shutdown()
    assert orchestrator.calls[0] == ("start",)
    assert orchestrator.calls[-1] == ("stop",)


async def test_shutdown_saves_position(engine, orchestrator, history, video):
    await engine.scan_devices()
    engine.select_device(LIVING_ROOM.id)
    engine.request_cast(video, resume=False)
    await engine.cast_task
    orchestrator.status = PlaybackStatus(state="playing", current_time=21.0, duration=100.0)
    await engine.shutdown()
    reopened = type(history)(history._db_path)
    assert await reopened.get_saved_position(str(video)) == 21.0
    reopened.close()


def test_settings_reports_missing_folder(make_engine, watch_dir, tmp_path):
    engine = make_engine(watch_folders=[watch_dir, tmp_path / "unplugged"])
    assert engine.settings()["watch_folders"] == [
        {"path": str(watch_dir), "available": True},
        {"path": str(tmp_path / "unplugged"), "available": False},
    ]


def test_update_settings_persists(engine, saved_configs, tmp_path):
    more = tmp_path / "more"
    more.mkdir()
    queue = engine.events.subscribe()
    result = engine.update_settings({"watch_folders": [str(more)], "recently_added_limit": 5})
    assert result["watch_folders"] == [{"path": str(more), "available": True}]
    assert result["recently_added_limit"] == 5
    assert saved_configs[-1].watch_folders == [more]
    assert engine.config.watch_folders == [more]
    assert drain(queue) == [{"type": "library_changed", "data": None}]


@pytest.mark.parametrize("changes", [
    {"color": "red"},
    {"watch_folders": "~/Movies"},
    {"watch_folders": ["relative/path"]},
    {"watch_folders": [""]},
    {"recently_added_limit": 0},
    {"recently_added_limit": True},
    {"recently_added_days": "7"},
])
def test_update_settings_rejects_bad_input(engine, saved_configs, changes):
    with pytest.raises(BadRequest):
        engine.update_settings(changes)
    assert saved_configs == []

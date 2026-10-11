from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from video_caster.casting.base import PlaybackStatus
from video_caster.config import Config
from video_caster.core.engine import Engine
from video_caster.discovery.device import Device, DeviceType
from video_caster.storage.history import HistoryStore


def make_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0")
    return path


@pytest.fixture
def history(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    yield store
    store.close()


@pytest.fixture
def watch_dir(tmp_path) -> Path:
    folder = tmp_path / "watch"
    make_video(folder / "Movie.mkv")
    return folder


@pytest.fixture
def video(watch_dir) -> Path:
    return watch_dir / "Movie.mkv"


LIVING_ROOM = Device(
    name="Living Room", device_type=DeviceType.CHROMECAST,
    address="192.168.10.17", port=8009, model="AI PONT JB",
)
BEDROOM = Device(
    name="Bedroom", device_type=DeviceType.DLNA,
    address="192.168.10.20", port=1400,
)


class FakeOrchestrator:
    """Stands in for CastOrchestrator: records calls, no network or ffmpeg."""

    def __init__(self) -> None:
        self.pin_callback = None
        self.status = PlaybackStatus()
        self.calls: list[tuple] = []
        self.cast_error: Exception | None = None
        self.cast_gate: asyncio.Event | None = None
        self.status_error: Exception | None = None
        self.command_error: Exception | None = None

    async def start(self) -> None:
        self.calls.append(("start",))

    async def stop(self) -> None:
        self.calls.append(("stop",))

    async def cast_file(self, file_path, device) -> None:
        self.calls.append(("cast_file", file_path, device.id))
        if self.cast_gate is not None:
            await self.cast_gate.wait()
        if self.cast_error is not None:
            raise self.cast_error
        self.status = PlaybackStatus(state="playing", current_time=0.0, duration=100.0)

    async def get_status(self) -> PlaybackStatus:
        if self.status_error is not None:
            raise self.status_error
        return self.status

    async def _command(self, *call) -> None:
        self.calls.append(call)
        if self.command_error is not None:
            raise self.command_error

    async def toggle_pause(self) -> None:
        await self._command("toggle_pause")

    async def seek(self, position: float) -> None:
        await self._command("seek", position)

    async def set_volume(self, level: float) -> None:
        await self._command("set_volume", level)

    async def stop_playback(self) -> None:
        await self._command("stop_playback")


def drain(queue) -> list[dict]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


@pytest.fixture
def orchestrator() -> FakeOrchestrator:
    return FakeOrchestrator()


@pytest.fixture
def saved_configs() -> list:
    return []


@pytest.fixture
def make_engine(orchestrator, history, watch_dir, saved_configs, tmp_path):
    def _make(*, devices=(LIVING_ROOM, BEDROOM), watch_folders=None, multicast_blocked=False):
        async def fake_scan(timeout: float):
            return list(devices)

        folders = [watch_dir] if watch_folders is None else watch_folders
        config = Config(watch_folders=folders, history_db_path=tmp_path / "history.db")
        return Engine(
            config, orchestrator, history,
            scan=fake_scan,
            persist_config=saved_configs.append,
            multicast_check=lambda: multicast_blocked,
            resume_delay=0.0,
            pin_timeout=0.2,
            tick_interval=0.01,
        )
    return _make


@pytest.fixture
def engine(make_engine) -> Engine:
    return make_engine()

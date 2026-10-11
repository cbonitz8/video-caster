"""Headless engine: owns devices, the current cast, history and settings."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from video_caster import library as lib
from video_caster.casting.base import PlaybackStatus
from video_caster.config import Config, save_config
from video_caster.core.errors import NotFound
from video_caster.core.events import EventBus
from video_caster.discovery.device import Device
from video_caster.discovery.scanner import scan_all
from video_caster.storage.history import HistoryStore
from video_caster.utils.network import multicast_blocked

log = logging.getLogger(__name__)

LOCAL_NETWORK_BLOCKED = (
    "Local Network access blocked: macOS is refusing multicast, so no devices can be "
    "found. System Settings > Privacy & Security > Local Network: enable Python. If it "
    "is already on, toggle it off and on, then restart the service."
)


class Orchestrator(Protocol):
    pin_callback: Callable[[str, str], Awaitable[str]] | None

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def cast_file(self, file_path: Path, device: Device) -> None: ...
    async def stop_playback(self) -> None: ...
    async def toggle_pause(self) -> None: ...
    async def seek(self, position: float) -> None: ...
    async def set_volume(self, level: float) -> None: ...
    async def get_status(self) -> PlaybackStatus: ...


def status_dict(status: PlaybackStatus, current_path: Path | None) -> dict:
    title = status.title
    if not title and current_path is not None:
        title = current_path.stem
    return {
        "state": status.state,
        "current_time": status.current_time,
        "duration": status.duration,
        "volume": status.volume,
        "title": title,
    }


def device_dict(device: Device) -> dict:
    return {
        "id": device.id,
        "name": device.name,
        "device_type": device.device_type.value,
        "address": device.address,
        "model": device.model,
    }


class Engine:
    def __init__(
        self,
        config: Config,
        orchestrator: Orchestrator,
        history: HistoryStore,
        *,
        scan: Callable[[float], Awaitable[list[Device]]] = scan_all,
        persist_config: Callable[[Config], None] = save_config,
        multicast_check: Callable[[], bool] = multicast_blocked,
        resume_delay: float = 1.0,
        pin_timeout: float = 120.0,
        tick_interval: float = 1.0,
    ) -> None:
        self.config = config
        self.history = history
        self.events = EventBus()
        self._orch = orchestrator
        self._scan = scan
        self._persist_config = persist_config
        self._multicast_check = multicast_check
        self._resume_delay = resume_delay
        self._pin_timeout = pin_timeout
        self._tick_interval = tick_interval

        self.devices: list[Device] = []
        self.selected_device: Device | None = None
        self.volume = 1.0
        self.cast_task: asyncio.Task | None = None
        self._scan_task: asyncio.Task | None = None
        self._scan_running = False
        self._scan_warning = ""
        self._current_path: Path | None = None
        self._watch_id: int | None = None
        self._pending: tuple[Path, bool] | None = None
        self._pin_request: dict | None = None
        self._pin_future: asyncio.Future | None = None
        self._last_status = status_dict(PlaybackStatus(), None)
        self._last_tick_error: str | None = None

    # -- State --

    def _devices_payload(self) -> dict:
        return {
            "devices": [device_dict(d) for d in self.devices],
            "selected_device": self.selected_device.id if self.selected_device else None,
            "scan": {"running": self._scan_running, "warning": self._scan_warning},
        }

    def state(self) -> dict:
        current = None
        if self._current_path is not None:
            current = {"path": str(self._current_path), "title": self._current_path.stem}
        pending = None
        if self._pending is not None:
            pending = {"path": str(self._pending[0]), "resume": self._pending[1]}
        return {
            "status": self._last_status,
            **self._devices_payload(),
            "current": current,
            "pending": pending,
            "pin_request": self._pin_request,
        }

    async def library(self) -> dict:
        return {
            "continue_watching": await lib.continue_watching(self.history),
            "up_next": await lib.up_next(self.history),
            "newly_added": await lib.newly_added(self.config),
        }

    async def is_in_history(self, path: Path) -> bool:
        return await self.history.has_file(str(path))

    # -- Devices --

    def request_scan(self) -> None:
        if self._scan_task is not None and not self._scan_task.done():
            return
        self._scan_task = asyncio.create_task(self.scan_devices())

    async def scan_devices(self) -> None:
        self._scan_running = True
        self.events.publish("devices", self._devices_payload())
        try:
            self.devices = await self._scan(5.0)
            if not self.devices and self._multicast_check():
                self._scan_warning = LOCAL_NETWORK_BLOCKED
            else:
                self._scan_warning = ""
        except Exception as e:
            log.exception("Device scan failed")
            self.events.publish("error", {"message": f"Device scan failed: {e}", "source": "scan"})
        finally:
            self._scan_running = False
            self.events.publish("devices", self._devices_payload())

    def select_device(self, device_id: str) -> None:
        for device in self.devices:
            if device.id == device_id:
                self.selected_device = device
                self.events.publish("devices", self._devices_payload())
                if self._pending is not None:
                    path, resume = self._pending
                    self._start_cast_task(path, resume)
                return
        raise NotFound(f"No device with id {device_id}")

    # -- Casting --

    def request_cast(self, path: Path, resume: bool) -> dict:
        if self.selected_device is None:
            self._pending = (path, resume)
            return {"status": "waiting_for_device", "device": None}
        self._start_cast_task(path, resume)
        return {"status": "casting", "device": self.selected_device.name}

    def _start_cast_task(self, path: Path, resume: bool) -> None:
        if self.cast_task is not None and not self.cast_task.done():
            self.cast_task.cancel()
        self._pending = None
        self.cast_task = asyncio.create_task(self._cast(path, resume, self.selected_device))

    async def _cast(self, path: Path, resume: bool, device: Device) -> None:
        try:
            await self._orch.cast_file(path, device)
            self._current_path = path
            status = await self._orch.get_status()
            self._watch_id = await self.history.record_play(
                file_path=str(path),
                file_name=path.name,
                device_id=device.id,
                device_name=device.name,
                duration=status.duration,
            )
            self.events.publish("library_changed", None)
            if resume:
                saved = await self.history.get_saved_position(str(path))
                if saved > 0:
                    await asyncio.sleep(self._resume_delay)  # let playback start first
                    await self._orch.seek(saved)
        except Exception as e:
            log.exception("Cast of %s failed", path)
            self.events.publish("error", {"message": f"Cast failed: {e}", "source": "cast"})

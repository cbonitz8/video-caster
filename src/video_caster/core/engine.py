"""Headless engine: owns devices, the current cast, history and settings."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from video_caster import library as lib
from video_caster.casting.base import PlaybackStatus
from video_caster.config import Config, save_config
from video_caster.core.errors import BadRequest, Conflict, NotFound
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

COMPLETED_PROGRESS = 0.9
_UNSAFE_PATH_CHARS = re.compile(r'["\\\x00-\x1f\x7f]')


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
        self._tick_task: asyncio.Task | None = None
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
            "newly_added": await lib.newly_added(self.config, self.history),
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
            await self._release_current("cast")
            await self._orch.cast_file(path, device)
            status = await self._orch.get_status()
            watch_id = await self.history.record_play(
                file_path=str(path),
                file_name=path.name,
                device_id=device.id,
                device_name=device.name,
                duration=status.duration,
            )
            # Set together, with no await between, so a tick never pairs one file's
            # watch id with another file's position.
            self._current_path = path
            self._watch_id = watch_id
            self.events.publish("library_changed", None)
            if resume:
                saved = await self.history.get_saved_position(str(path))
                if saved > 0:
                    await asyncio.sleep(self._resume_delay)  # let playback start first
                    await self._orch.seek(saved)
        except Exception as e:
            log.exception("Cast of %s failed", path)
            self.events.publish("error", {"message": f"Cast failed: {e}", "source": "cast"})

    # -- Playback --

    async def tick(self) -> None:
        try:
            status = await self._orch.get_status()
            payload = status_dict(status, self._current_path)
            if payload != self._last_status or status.state == "playing":
                self._last_status = payload
                self.events.publish("status", payload)
            if self._watch_id is not None and status.current_time > 0:
                await self.history.update_position(self._watch_id, status.current_time)
                if status.duration > 0:
                    await self.history.update_duration(self._watch_id, status.duration)
                    if status.progress >= COMPLETED_PROGRESS:
                        await self.history.mark_completed(self._watch_id)
                        self._watch_id = None
                        self.events.publish("library_changed", None)
            self._last_tick_error = None
        except Exception as e:
            message = f"Status update failed: {e}"
            # A vanished device fails every tick; report each distinct failure once.
            if message != self._last_tick_error:
                log.exception(message)
                self.events.publish("error", {"message": message, "source": "status"})
            self._last_tick_error = message

    async def _tick_loop(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self._tick_interval)

    async def toggle_pause(self) -> None:
        await self._orch.toggle_pause()

    async def seek(self, position: float | None = None, offset: float | None = None) -> None:
        if (position is None) == (offset is None):
            raise BadRequest("Give exactly one of position or offset")
        if offset is not None:
            status = await self._orch.get_status()
            target = max(0.0, status.current_time + offset)
            if status.duration > 0:
                target = min(target, status.duration)
        else:
            target = max(0.0, position)
        await self._orch.seek(target)

    async def set_volume(self, level: float) -> None:
        self.volume = max(0.0, min(1.0, level))
        await self._orch.set_volume(self.volume)

    async def stop(self) -> None:
        self._pending = None
        await self._cancel_cast()
        await self._release_current("stop")
        await self._orch.stop_playback()
        self.events.publish("library_changed", None)

    async def _cancel_cast(self) -> None:
        task = self.cast_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _release_current(self, source: str) -> None:
        """Save the current file's position, then forget it."""
        watch_id = self._watch_id
        self._watch_id = None
        self._current_path = None
        if watch_id is None:
            return
        try:
            status = await self._orch.get_status()
            if status.current_time > 0:
                await self.history.force_update_position(watch_id, status.current_time)
        except Exception as e:
            log.exception("Couldn't save position")
            self.events.publish("error", {"message": f"Couldn't save position: {e}", "source": source})

    # -- Lifecycle --

    async def start(self) -> None:
        self._orch.pin_callback = self.pin_callback
        await self._orch.start()
        self.request_scan()
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def shutdown(self) -> None:
        tasks = [t for t in (self._tick_task, self._scan_task, self.cast_task) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._release_current("shutdown")
        await self._orch.stop()
        self.history.close()

    # -- AirPlay pairing --

    async def pin_callback(self, device_name: str, protocol: str) -> str:
        if self._pin_future is not None and not self._pin_future.done():
            raise Conflict("Another pairing is already waiting for a PIN")
        self._pin_future = asyncio.get_running_loop().create_future()
        self._pin_request = {"device_name": device_name, "protocol": protocol}
        self.events.publish("pin_required", self._pin_request)
        try:
            return await asyncio.wait_for(self._pin_future, self._pin_timeout)
        except TimeoutError:
            raise TimeoutError(
                f"No PIN entered for {device_name} within {self._pin_timeout:.0f}s"
            ) from None
        finally:
            self._pin_request = None
            self._pin_future = None
            self.events.publish("pin_resolved", {"device_name": device_name})

    def submit_pin(self, pin: str) -> None:
        if self._pin_future is None or self._pin_future.done():
            raise Conflict("No pairing is waiting for a PIN")
        self._pin_future.set_result(pin)

    # -- Settings --

    def settings(self) -> dict:
        return {
            "watch_folders": [
                {"path": str(f), "available": f.is_dir()} for f in self.config.watch_folders
            ],
            "recently_added_limit": self.config.recently_added_limit,
            "recently_added_days": self.config.recently_added_days,
        }

    def update_settings(self, changes: dict) -> dict:
        allowed = {"watch_folders", "recently_added_limit", "recently_added_days"}
        unknown = set(changes) - allowed
        if unknown:
            raise BadRequest(f"Unknown settings: {', '.join(sorted(unknown))}")
        updates: dict = {}
        if "watch_folders" in changes:
            folders = changes["watch_folders"]
            if not isinstance(folders, list) or not all(isinstance(p, str) and p for p in folders):
                raise BadRequest("watch_folders must be a list of absolute paths")
            # config.toml stores these as plain TOML strings, so these characters would corrupt it.
            if any(_UNSAFE_PATH_CHARS.search(p) for p in folders):
                raise BadRequest("watch_folders paths can't contain quotes, backslashes or control characters")
            paths = [Path(p).expanduser() for p in folders]
            if not all(p.is_absolute() for p in paths):
                raise BadRequest("watch_folders must be a list of absolute paths")
            updates["watch_folders"] = paths
        for key in ("recently_added_limit", "recently_added_days"):
            if key in changes:
                value = changes[key]
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise BadRequest(f"{key} must be a positive integer")
                updates[key] = value
        candidate = dataclasses.replace(self.config, **updates)
        self._persist_config(candidate)
        self.config = candidate
        self.events.publish("library_changed", None)
        return self.settings()

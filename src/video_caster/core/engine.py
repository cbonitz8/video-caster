"""Headless engine: owns devices, the current cast, history and settings."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from video_caster import library as lib
from video_caster.casting.base import DeviceRequestFailed, PlaybackStatus, RequestPin
from video_caster.catalogue import WATCHED_AT, Catalogue, WatchStates
from video_caster.config import Config, save_config
from video_caster.core import paths
from video_caster.core.errors import BadRequest, Conflict, DeviceError, NotFound
from video_caster.core.events import EventBus
from video_caster.discovery.device import Device
from video_caster.discovery.scanner import scan_all
from video_caster.posters import POSTERS_DIR
from video_caster.storage.history import HistoryStore
from video_caster.storage.scanner import scan_watch_folders
from video_caster.titles import display_title
from video_caster.utils.network import multicast_blocked

log = logging.getLogger(__name__)

LOCAL_NETWORK_BLOCKED = (
    "Local Network access blocked: macOS is refusing multicast, so no devices can be "
    "found. System Settings > Privacy & Security > Local Network: enable Python. If it "
    "is already on, toggle it off and on, then restart the service."
)

class Orchestrator(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def cast_file(
        self, file_path: Path, device: Device, request_pin: RequestPin
    ) -> None: ...
    async def stop_playback(self) -> None: ...
    async def toggle_pause(self) -> None: ...
    async def seek(self, position: float) -> None: ...
    async def set_volume(self, level: float) -> None: ...
    async def get_status(self) -> PlaybackStatus: ...


def status_dict(status: PlaybackStatus, current_path: Path | None) -> dict:
    title = status.title
    if not title and current_path is not None:
        title = display_title(current_path)["title"]
    return {
        "state": status.state,
        "current_time": status.current_time,
        "duration": status.duration,
        "volume": status.volume,
        "title": title,
    }


@contextmanager
def _device_request() -> Iterator[None]:
    try:
        yield
    except DeviceRequestFailed as e:
        raise DeviceError(str(e)) from e


def file_entry(path: Path) -> dict:
    return {"path": str(path), **display_title(path)}


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
        posters_dir: Path = POSTERS_DIR,
    ) -> None:
        self.config = config
        self.posters_dir = posters_dir
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
        self._next_path: Path | None = None
        self._casting: Path | None = None
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

    def _current_payload(self) -> dict:
        current = None
        if self._current_path is not None:
            nxt = None if self._next_path is None else file_entry(self._next_path)
            current = {**file_entry(self._current_path), "next": nxt}
        pending = None
        if self._pending is not None:
            pending = {**file_entry(self._pending[0]), "resume": self._pending[1]}
        casting = None if self._casting is None else file_entry(self._casting)
        return {"current": current, "pending": pending, "casting": casting}

    def _publish_current(self) -> None:
        self.events.publish("current", self._current_payload())

    def state(self) -> dict:
        return {
            "status": self._last_status,
            **self._devices_payload(),
            **self._current_payload(),
            "pin_request": self._pin_request,
        }

    def subscribe(self) -> asyncio.Queue:
        return self.events.subscribe()

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.events.unsubscribe(queue)

    # -- Library --

    async def library(self) -> dict:
        return await lib.build_library(self.config, self.history, self.posters_dir)

    async def browse(self, folder: Path | None) -> list[dict]:
        entries = await asyncio.to_thread(paths.browse, folder, self.config.watch_folders)
        files = [e for e in entries if not e["is_dir"]]
        if files:
            await lib.attach_positions(self.history, files)
        return entries

    def poster_file(self, name: str) -> Path:
        return paths.poster_file(self.posters_dir, name)

    async def check_castable(self, path: Path, *, local: bool) -> None:
        await paths.check_castable(
            path, self.config.watch_folders, local=local, ever_cast=self._ever_cast
        )

    async def _ever_cast(self, path: Path) -> bool:
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
            self._refresh_selected_device()
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

    def _refresh_selected_device(self) -> None:
        if self.selected_device is None:
            return
        for device in self.devices:
            if device.id == self.selected_device.id:
                self.selected_device = device
                return

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
            self._publish_current()
            return {"status": "waiting_for_device", "device": None}
        self._start_cast_task(path, resume)
        return {"status": "casting", "device": self.selected_device.name}

    def _start_cast_task(self, path: Path, resume: bool) -> None:
        if self.cast_task is not None and not self.cast_task.done():
            self.cast_task.cancel()
        self._pending = None
        self._casting = path
        self._publish_current()
        self.cast_task = asyncio.create_task(self._cast(path, resume, self.selected_device))

    async def _cast(self, path: Path, resume: bool, device: Device) -> None:
        try:
            await self._release_current("cast")
            await self._orch.cast_file(path, device, self.request_pin)
            status = await self._orch.get_status()
            next_path = await self._next_after(path)
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
            self._next_path = next_path
            self._casting = None
            self._publish_current()
            self.events.publish("library_changed", None)
            if resume:
                states = WatchStates(await self.history.meaningful_records())
                saved = states.resume_position(path)
                if saved is not None:
                    await asyncio.sleep(self._resume_delay)  # let playback start first
                    await self._orch.seek(saved)
        except Exception as e:
            log.exception("Cast of %s failed", path)
            self.events.publish("error", {"message": f"Cast failed: {e}", "source": "cast"})
        finally:
            # A replaced cast's task finishes after its successor started; leave the successor's flag.
            if self._casting is not None and asyncio.current_task() is self.cast_task:
                self._casting = None
                self._publish_current()

    async def _next_after(self, path: Path) -> Path | None:
        try:
            files = await scan_watch_folders(self.config.watch_folders, max_depth=10)
        except OSError as e:
            log.warning("No next episode: couldn't scan the watch folders: %s", e)
            return None
        return Catalogue([f.path for f in files]).next_after(path)

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
                    if status.progress >= WATCHED_AT:
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
        with _device_request():
            await self._orch.toggle_pause()

    async def seek(self, position: float | None = None, offset: float | None = None) -> None:
        if (position is None) == (offset is None):
            raise BadRequest("Give exactly one of position or offset")
        with _device_request():
            if offset is not None:
                status = await self._orch.get_status()
                target = max(0.0, status.current_time + offset)
                if status.duration > 0:
                    target = min(target, status.duration)
            else:
                target = max(0.0, position)
            await self._orch.seek(target)

    def next_episode(self) -> Path:
        if self._current_path is None:
            raise Conflict("Nothing is playing")
        if self._next_path is None:
            raise Conflict("No next episode")
        return self._next_path

    async def set_volume(self, level: float) -> None:
        self.volume = max(0.0, min(1.0, level))
        with _device_request():
            await self._orch.set_volume(self.volume)

    async def stop(self) -> None:
        had_pending = self._pending is not None
        self._pending = None
        if had_pending:
            self._publish_current()
        await self._cancel_cast()
        await self._release_current("stop")
        try:
            with _device_request():
                await self._orch.stop_playback()
        finally:
            self.events.publish("library_changed", None)

    async def _cancel_cast(self) -> None:
        task = self.cast_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _release_current(self, source: str) -> None:
        """Save the current file's position, then forget it."""
        watch_id = self._watch_id
        had_current = self._current_path is not None
        self._watch_id = None
        self._current_path = None
        self._next_path = None
        if had_current:
            self._publish_current()
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

    async def request_pin(self, device_name: str) -> str:
        if self._pin_future is not None and not self._pin_future.done():
            raise Conflict("Another pairing is already waiting for a PIN")
        self._pin_future = asyncio.get_running_loop().create_future()
        self._pin_request = {"device_name": device_name}
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
        }

    def update_settings(self, changes: dict) -> dict:
        allowed = {"watch_folders", "recently_added_limit"}
        unknown = set(changes) - allowed
        if unknown:
            raise BadRequest(f"Unknown settings: {', '.join(sorted(unknown))}")
        updates: dict = {}
        if "watch_folders" in changes:
            folders = changes["watch_folders"]
            if not isinstance(folders, list) or not all(isinstance(p, str) and p for p in folders):
                raise BadRequest("watch_folders must be a list of absolute paths")
            if any("\0" in p for p in folders):
                raise BadRequest("watch_folders paths can't contain NUL characters")
            paths = [Path(p).expanduser() for p in folders]
            if not all(p.is_absolute() for p in paths):
                raise BadRequest("watch_folders must be a list of absolute paths")
            updates["watch_folders"] = paths
        if "recently_added_limit" in changes:
            limit = changes["recently_added_limit"]
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise BadRequest("recently_added_limit must be a positive integer")
            updates["recently_added_limit"] = limit
        candidate = dataclasses.replace(self.config, **updates)
        self._persist_config(candidate)
        self.config = candidate
        self.events.publish("library_changed", None)
        return self.settings()

"""Video Caster — Textual TUI application."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import (
    DirectoryTree, Footer, Header, Input, Label, TabbedContent, TabPane,
)
from textual.screen import ModalScreen

from video_caster.casting.base import PlaybackStatus
from video_caster.casting.orchestrator import CastOrchestrator
from video_caster.config import Config, load_config, save_config
from video_caster.discovery.device import Device
from video_caster.discovery.scanner import scan_all
from video_caster.storage.history import HistoryStore
from video_caster.storage.scanner import scan_watch_folders
from video_caster.server.web_remote import WebRemoteServer
from video_caster.ui.branding import BrandingHeader
from video_caster.ui.device_list import DeviceList, DeviceSelected
from video_caster.ui.file_browser import VideoBrowser
from video_caster.storage.episode import find_next_episode, parse_episode
from video_caster.ui.home import ContinueWatchingList, FileChosen, NewlyAddedList, UpNextEntry, UpNextList
from video_caster.ui.playback_controls import PlaybackControls
from video_caster.ui.qr_widget import QRCodeWidget
from video_caster.ui.settings_screen import SettingsChanged, SettingsScreen
from video_caster.ui.watch_folders import WatchFolderBrowser

log = logging.getLogger(__name__)


class PinInputScreen(ModalScreen[str]):
    """Modal for Apple TV PIN entry."""

    def __init__(self, device_name: str, protocol: str) -> None:
        self._device_name = device_name
        self._protocol = protocol
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Label(f"Enter PIN shown on {self._device_name} ({self._protocol}):")
        yield Input(placeholder="PIN", id="pin-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


class VideoCasterApp(App):
    """Main Video Caster application."""

    TITLE = "Video Caster"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("space", "toggle_pause", "Play/Pause", priority=True),
        Binding("s", "stop_playback", "Stop", priority=True),
        Binding("d", "scan_devices", "Scan Devices", priority=True),
        Binding("r", "refresh_files", "Refresh", priority=True),
        Binding("left", "seek_back", "-10s", priority=True),
        Binding("right", "seek_forward", "+10s", priority=True),
        Binding("comma", "seek_back_large", "-60s", priority=True),
        Binding("full_stop", "seek_forward_large", "+60s", priority=True),
        Binding("[", "volume_down", "Vol-", priority=True),
        Binding("]", "volume_up", "Vol+", priority=True),
        Binding("o", "open_settings", "Settings", priority=True),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self._config = config or load_config()
        self._orchestrator = CastOrchestrator()
        self._history = HistoryStore(self._config.history_db_path)
        self._devices: list[Device] = []
        self._selected_device: Device | None = None
        self._volume = 1.0
        self._current_watch_id: int | None = None
        self._current_file_path: Path | None = None
        self._pending_file: Path | None = None
        self._pending_resume: bool = False
        self._web_remote = WebRemoteServer(self, port=self._config.web_remote_port)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="left-panel"):
            yield BrandingHeader()
            with TabbedContent():
                with TabPane("Home", id="home-tab"):
                    yield ContinueWatchingList(id="continue-watching")
                    yield UpNextList(id="up-next")
                    yield NewlyAddedList(id="newly-added")
                with TabPane("Browse", id="browse-tab"):
                    yield WatchFolderBrowser(
                        folders=self._config.watch_folders,
                        id="watch-folder-browser",
                    )
                with TabPane("Manual", id="manual-tab"):
                    yield VideoBrowser(Path.home(), id="manual-browser")
        with Vertical(id="right-panel"):
            yield Container(DeviceList(id="device-list"), id="device-panel")
            yield Container(QRCodeWidget(id="qr-code"), id="qr-panel")
            yield Container(PlaybackControls(id="playback-controls"), id="playback-panel")
        yield Footer()

    async def on_mount(self) -> None:
        self._orchestrator.pin_callback = self._pin_callback
        await self._orchestrator.start()
        await self._web_remote.start()
        qr = self.query_one("#qr-code", QRCodeWidget)
        qr.set_url(self._web_remote.url)
        self.run_worker(self._initial_scan(), exclusive=True, group="scan")
        self.run_worker(self._load_home_data(), group="home")
        self.set_interval(1.0, self._poll_status)

    async def _initial_scan(self) -> None:
        self._update_status("Scanning for devices...")
        try:
            self._devices = await scan_all(timeout=5.0)
            device_list = self.query_one("#device-list", DeviceList)
            device_list.set_devices(self._devices)
            # Broadcast updated device list to web remote
            await self._web_remote.broadcast_devices([
                {"id": d.id, "name": d.name, "device_type": d.device_type.value,
                 "address": d.address, "model": d.model}
                for d in self._devices
            ])
            if self._devices:
                self._update_status(f"Found {len(self._devices)} device(s)")
            else:
                self._update_status("No devices found")
        except Exception as e:
            self._update_status(f"Scan failed: {e}")

    async def _load_home_data(self) -> None:
        """Load continue watching, up next, and newly added data."""
        try:
            records = await self._history.get_continue_watching(limit=10)
            cw = self.query_one("#continue-watching", ContinueWatchingList)
            cw.set_records(records)
        except Exception as e:
            log.error("Failed to load continue watching: %s", e)

        try:
            entries = await self._build_up_next()
            un = self.query_one("#up-next", UpNextList)
            un.set_entries(entries)
        except Exception as e:
            log.error("Failed to load up next: %s", e)

        try:
            files = await scan_watch_folders(
                self._config.watch_folders,
                max_depth=10,
            )
            na = self.query_one("#newly-added", NewlyAddedList)
            na.set_files(files[:self._config.recently_added_limit])
        except Exception as e:
            log.error("Failed to scan watch folders: %s", e)

    async def _build_up_next(self) -> list[UpNextEntry]:
        """Find next episodes for all completed/nearly-completed episodes."""
        completed = await self._history.get_completed_or_nearly(limit=50)
        seen_next: set[str] = set()
        entries: list[UpNextEntry] = []

        for rec in completed:
            path = Path(rec.file_path)
            if parse_episode(path) is None:
                continue
            nxt = find_next_episode(path)
            if nxt is None or str(nxt) in seen_next:
                continue
            # Don't suggest episodes that are already in history
            saved = await self._history.get_saved_position(str(nxt))
            if saved > 0:
                continue
            seen_next.add(str(nxt))
            entries.append(UpNextEntry(
                next_path=nxt,
                next_name=nxt.name,
                watched_name=rec.file_name,
            ))

        return entries

    # -- File selection handlers (from any tab) --

    def _start_cast(self, path: Path, resume: bool = False) -> None:
        if self._selected_device is None:
            self._pending_file = path
            self._pending_resume = resume
            self._update_status(f"Selected: {path.name} — now pick a device")
            self.notify("Now select a device to cast to")
            return
        self._pending_file = None
        self._pending_resume = False
        self.run_worker(
            self._cast_file(path, resume=resume),
            exclusive=True,
            group="cast",
        )

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self._start_cast(event.path)

    def on_file_chosen(self, event: FileChosen) -> None:
        self._start_cast(event.path, resume=True)

    def on_device_selected(self, event: DeviceSelected) -> None:
        self._selected_device = event.device
        if self._pending_file:
            self._update_status(f"Selected: {event.device.name}")
            self._start_cast(self._pending_file, self._pending_resume)
        else:
            self._update_status(f"Selected: {event.device.name}")

    async def _cast_file(self, path: Path, resume: bool = False) -> None:
        if not self._selected_device:
            return
        self._update_status(f"Casting {path.name}...")
        try:
            await self._orchestrator.cast_file(path, self._selected_device)
            self._current_file_path = path
            self._update_status(f"Playing: {path.name}")

            # Record in history
            device = self._selected_device
            status = await self._orchestrator.get_status()
            self._current_watch_id = await self._history.record_play(
                file_path=str(path),
                file_name=path.name,
                device_id=device.id,
                device_name=device.name,
                duration=status.duration,
            )

            # Resume from saved position if selected from Continue Watching
            if resume:
                saved = await self._history.get_saved_position(str(path))
                if saved > 0:
                    await asyncio.sleep(1.0)  # let playback start before seeking
                    await self._orchestrator.seek(saved)
                    self._update_status(f"Resumed: {path.name}")

        except Exception as e:
            self._update_status(f"Cast failed: {e}")
            self.notify(f"Cast failed: {e}", severity="error")

    async def _poll_status(self) -> None:
        try:
            status = await self._orchestrator.get_status()
            controls = self.query_one("#playback-controls", PlaybackControls)
            controls.update_status(status)

            # Broadcast to web remote clients — use file path as title fallback
            title = status.title
            if not title and self._current_file_path:
                title = self._current_file_path.stem
            await self._web_remote.broadcast_status({
                "state": status.state,
                "current_time": status.current_time,
                "duration": status.duration,
                "volume": status.volume,
                "title": title,
            })

            # Update history position and duration
            if self._current_watch_id and status.current_time > 0:
                await self._history.update_position(self._current_watch_id, status.current_time)

                # Backfill duration once device reports it
                if status.duration > 0:
                    await self._history.update_duration(self._current_watch_id, status.duration)

                    # Mark completed at 90%
                    if status.progress >= 0.9:
                        await self._history.mark_completed(self._current_watch_id)
                        self._current_watch_id = None
        except Exception:
            pass

    async def _pin_callback(self, device_name: str, protocol: str) -> str:
        screen = PinInputScreen(device_name, protocol)
        return await self.push_screen_wait(screen)

    # -- Settings --

    def on_settings_changed(self, event: SettingsChanged) -> None:
        """Reload config after settings are saved."""
        self._config = load_config()
        # Refresh watch folder browser
        try:
            wfb = self.query_one("#watch-folder-browser", WatchFolderBrowser)
            wfb.set_folders(self._config.watch_folders)
        except Exception:
            pass
        # Refresh newly added
        self.run_worker(self._load_home_data(), group="home")
        self.notify("Settings saved")

    # -- Actions --

    def action_toggle_pause(self) -> None:
        self.run_worker(self._orchestrator.toggle_pause(), group="control")

    def action_stop_playback(self) -> None:
        async def _stop():
            if self._current_watch_id:
                try:
                    status = await self._orchestrator.get_status()
                    if status.current_time > 0:
                        await self._history.force_update_position(
                            self._current_watch_id, status.current_time,
                        )
                except Exception:
                    pass
            await self._orchestrator.stop_playback()
            self._current_watch_id = None
            self._current_file_path = None
        self.run_worker(_stop(), group="control")
        self._update_status("Stopped")

    def action_scan_devices(self) -> None:
        self.run_worker(self._initial_scan(), exclusive=True, group="scan")

    def action_refresh_files(self) -> None:
        self.run_worker(self._load_home_data(), group="home")
        self.notify("Refreshing files...")

    def action_open_settings(self) -> None:
        self.push_screen(SettingsScreen(watch_folders=self._config.watch_folders))

    def _seek_relative(self, offset: float) -> None:
        async def _do_seek():
            status = await self._orchestrator.get_status()
            target = max(0.0, status.current_time + offset)
            if status.duration > 0:
                target = min(target, status.duration)
            await self._orchestrator.seek(target)

        self.run_worker(_do_seek(), group="control")

    def action_seek_back(self) -> None:
        self._seek_relative(-10.0)

    def action_seek_forward(self) -> None:
        self._seek_relative(10.0)

    def action_seek_back_large(self) -> None:
        self._seek_relative(-60.0)

    def action_seek_forward_large(self) -> None:
        self._seek_relative(60.0)

    def action_volume_up(self) -> None:
        self._volume = min(1.0, self._volume + 0.1)
        self.run_worker(self._orchestrator.set_volume(self._volume), group="control")

    def action_volume_down(self) -> None:
        self._volume = max(0.0, self._volume - 0.1)
        self.run_worker(self._orchestrator.set_volume(self._volume), group="control")

    # -- Web remote integration --

    def auto_select_device(self) -> Device | None:
        """Auto-select the first available device if none is selected."""
        if self._selected_device is not None:
            return self._selected_device
        if not self._devices:
            return None
        self._selected_device = self._devices[0]
        self._update_status(f"Auto-selected: {self._selected_device.name}")
        return self._selected_device

    def cast_from_remote(self, path: Path, resume: bool = False) -> None:
        """Called by web remote to start casting a file."""
        self._start_cast(path, resume=resume)

    def select_device_from_remote(self, device_id: str) -> None:
        """Called by web remote to select a device by ID."""
        for device in self._devices:
            if device.id == device_id:
                self._selected_device = device
                self._update_status(f"Selected: {device.name}")
                if self._pending_file:
                    self._start_cast(self._pending_file, self._pending_resume)
                return

    def scan_devices_from_remote(self) -> None:
        """Called by web remote to trigger a device scan."""
        self.run_worker(self._initial_scan(), exclusive=True, group="scan")

    def _update_status(self, msg: str) -> None:
        self.sub_title = msg

    async def action_quit(self) -> None:
        # Save final position before killing playback
        if self._current_watch_id:
            try:
                status = await self._orchestrator.get_status()
                if status.current_time > 0:
                    await self._history.force_update_position(
                        self._current_watch_id, status.current_time,
                    )
            except Exception:
                pass
        await self._web_remote.stop()
        await self._orchestrator.stop()
        self._history.close()
        self.exit()

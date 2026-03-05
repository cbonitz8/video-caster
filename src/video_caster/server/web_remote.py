"""Web remote control server — aiohttp with REST API and WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web, WSMsgType

from video_caster.server.web_remote_html import REMOTE_HTML
from video_caster.storage.scanner import scan_watch_folders
from video_caster.utils.network import get_lan_ip

if TYPE_CHECKING:
    from video_caster.app import VideoCasterApp

log = logging.getLogger(__name__)


class WebRemoteServer:
    def __init__(self, app: VideoCasterApp, port: int = 8484) -> None:
        self._app = app
        self._port = port
        self._web_app = web.Application()
        self._runner: web.AppRunner | None = None
        self._ws_clients: set[web.WebSocketResponse] = set()
        self._setup_routes()

    @property
    def url(self) -> str:
        return f"http://{get_lan_ip()}:{self._port}"

    def _setup_routes(self) -> None:
        r = self._web_app.router
        r.add_get("/", self._handle_index)
        r.add_get("/api/status", self._handle_status)
        r.add_get("/api/devices", self._handle_devices)
        r.add_get("/api/files", self._handle_files)
        r.add_get("/api/files/browse", self._handle_browse)
        r.add_post("/api/playback/toggle", self._handle_toggle)
        r.add_post("/api/playback/stop", self._handle_stop)
        r.add_post("/api/playback/seek", self._handle_seek)
        r.add_post("/api/playback/volume", self._handle_volume)
        r.add_post("/api/cast", self._handle_cast)
        r.add_post("/api/device/select", self._handle_device_select)
        r.add_post("/api/devices/scan", self._handle_device_scan)
        r.add_get("/ws", self._handle_ws)

    async def start(self) -> None:
        self._runner = web.AppRunner(self._web_app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await site.start()
        log.info("Web remote listening on %s", self.url)

    async def stop(self) -> None:
        # Close all websockets
        for ws_resp in list(self._ws_clients):
            await ws_resp.close()
        self._ws_clients.clear()
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ─── Broadcast helpers ───

    async def broadcast_status(self, status_dict: dict) -> None:
        msg = json.dumps({"type": "status", "data": status_dict})
        await self._broadcast(msg)

    async def broadcast_devices(self, devices_list: list[dict]) -> None:
        msg = json.dumps({"type": "devices", "data": devices_list})
        await self._broadcast(msg)

    async def _broadcast(self, msg: str) -> None:
        dead: list[web.WebSocketResponse] = []
        for ws_resp in list(self._ws_clients):  # snapshot to avoid set-changed-during-iteration
            try:
                await ws_resp.send_str(msg)
            except Exception:
                dead.append(ws_resp)
        for d in dead:
            self._ws_clients.discard(d)

    # ─── Route handlers ───

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=REMOTE_HTML, content_type="text/html")

    async def _handle_status(self, request: web.Request) -> web.Response:
        status = await self._app._orchestrator.get_status()
        d = self._status_to_dict(status)
        if not d["title"] and self._app._current_file_path:
            d["title"] = self._app._current_file_path.stem
        return web.json_response(d)

    async def _handle_devices(self, request: web.Request) -> web.Response:
        return web.json_response(self._devices_to_list())

    async def _handle_files(self, request: web.Request) -> web.Response:
        # Continue watching
        records = await self._app._history.get_continue_watching(limit=10)
        cw = [
            {
                "file_path": r.file_path,
                "file_name": r.file_name,
                "position": r.position,
                "duration": r.duration,
                "progress": r.progress,
            }
            for r in records
        ]

        # Recently added
        files = await scan_watch_folders(
            self._app._config.watch_folders,
            max_depth=10,
        )
        ra = [
            {
                "path": str(f.path),
                "name": f.name,
                "size": f.size,
                "mtime_ago": f.mtime_ago,
            }
            for f in files[: self._app._config.recently_added_limit]
        ]

        # Watch folder roots for browse tab
        wf = [
            {"path": str(f), "name": f.name, "is_dir": True}
            for f in self._app._config.watch_folders
            if f.is_dir()
        ]

        return web.json_response({
            "continue_watching": cw,
            "recently_added": ra,
            "watch_folders": wf,
        })

    async def _handle_browse(self, request: web.Request) -> web.Response:
        req_path = request.query.get("path", "")
        if not req_path:
            # Return watch folder roots
            folders = [
                {"path": str(f), "name": f.name, "is_dir": True}
                for f in self._app._config.watch_folders
                if f.is_dir()
            ]
            return web.json_response(folders)

        target = Path(req_path).resolve()
        # Security: ensure path is under a watch folder
        if not self._is_under_watch_folder(target):
            raise web.HTTPForbidden(text="Path not in watch folders")

        if not target.is_dir():
            raise web.HTTPNotFound()

        from video_caster.transcoding.formats import VIDEO_EXTENSIONS

        entries: list[dict] = []
        try:
            for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    entries.append({"path": str(child), "name": child.name, "is_dir": True})
                elif child.suffix.lower() in VIDEO_EXTENSIONS:
                    stat = child.stat()
                    entries.append({
                        "path": str(child),
                        "name": child.name,
                        "is_dir": False,
                        "size": stat.st_size,
                    })
        except PermissionError:
            raise web.HTTPForbidden(text="Permission denied")

        return web.json_response(entries)

    async def _handle_toggle(self, request: web.Request) -> web.Response:
        await self._app._orchestrator.toggle_pause()
        return web.json_response({"ok": True})

    async def _handle_stop(self, request: web.Request) -> web.Response:
        self._app.action_stop_playback()
        return web.json_response({"ok": True})

    async def _handle_seek(self, request: web.Request) -> web.Response:
        data = await request.json()
        position = float(data.get("position", 0))
        await self._app._orchestrator.seek(position)
        return web.json_response({"ok": True})

    async def _handle_volume(self, request: web.Request) -> web.Response:
        data = await request.json()
        level = float(data.get("level", 1.0))
        self._app._volume = level
        await self._app._orchestrator.set_volume(level)
        return web.json_response({"ok": True})

    async def _handle_cast(self, request: web.Request) -> web.Response:
        data = await request.json()
        path = Path(data.get("path", ""))
        resume = bool(data.get("resume", False))

        if not path.is_file():
            raise web.HTTPNotFound(text="File not found")

        # Security: allow files in watch folders or in watch history
        resolved = path.resolve()
        if not self._is_under_watch_folder(resolved) and not await self._is_in_history(resolved):
            raise web.HTTPForbidden(text="Path not in watch folders")

        # Auto-select device if none selected
        if self._app._selected_device is None:
            device = self._app.auto_select_device()
            if device is None:
                return web.json_response(
                    {"ok": False, "error": "No devices available. Go to Devices tab and scan."},
                    status=400,
                )

        self._app.cast_from_remote(path, resume=resume)
        return web.json_response({
            "ok": True,
            "device": self._app._selected_device.name,
        })

    async def _handle_device_select(self, request: web.Request) -> web.Response:
        data = await request.json()
        device_id = data.get("device_id", "")
        self._app.select_device_from_remote(device_id)
        return web.json_response({"ok": True})

    async def _handle_device_scan(self, request: web.Request) -> web.Response:
        self._app.scan_devices_from_remote()
        return web.json_response({"ok": True})

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws_resp = web.WebSocketResponse()
        await ws_resp.prepare(request)
        self._ws_clients.add(ws_resp)
        log.debug("WebSocket client connected (%d total)", len(self._ws_clients))

        # Send initial state
        try:
            status = await self._app._orchestrator.get_status()
            status_d = self._status_to_dict(status)
            if not status_d["title"] and self._app._current_file_path:
                status_d["title"] = self._app._current_file_path.stem
            await ws_resp.send_str(json.dumps({
                "type": "status",
                "data": status_d,
            }))
            await ws_resp.send_str(json.dumps({
                "type": "devices",
                "data": self._devices_to_list(),
            }))
        except Exception as e:
            log.warning("Failed to send initial WS state: %s", e)

        try:
            async for msg in ws_resp:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            self._ws_clients.discard(ws_resp)
            log.debug("WebSocket client disconnected (%d remaining)", len(self._ws_clients))

        return ws_resp

    # ─── Helpers ───

    def _status_to_dict(self, status) -> dict:
        return {
            "state": status.state,
            "current_time": status.current_time,
            "duration": status.duration,
            "volume": status.volume,
            "title": status.title,
        }

    def _devices_to_list(self) -> list[dict]:
        return [
            {
                "id": d.id,
                "name": d.name,
                "device_type": d.device_type.value,
                "address": d.address,
                "model": d.model,
            }
            for d in self._app._devices
        ]

    async def _is_in_history(self, path: Path) -> bool:
        """Check if a file path exists in the watch history (previously cast)."""
        saved = await self._app._history.get_saved_position(str(path))
        return saved > 0

    def _is_under_watch_folder(self, path: Path) -> bool:
        resolved = path.resolve()
        for folder in self._app._config.watch_folders:
            try:
                resolved.relative_to(folder.resolve())
                return True
            except ValueError:
                continue
        return False

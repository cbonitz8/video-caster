"""HTTP JSON API and WebSocket events over the engine."""

from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path

from aiohttp import web
from pychromecast.error import RequestTimeout

from video_caster.core import auth, paths
from video_caster.core.engine import Engine
from video_caster.core.errors import BadRequest, EngineError, Forbidden, NotFound

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@web.middleware
async def _error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPException as e:
        if e.status < 400:
            raise
        return web.json_response({"error": e.reason}, status=e.status)
    except EngineError as e:
        return web.json_response({"error": str(e)}, status=e.status)
    except (RequestTimeout, TimeoutError) as e:
        log.warning("Device did not respond on %s %s: %s", request.method, request.path, e)
        return web.json_response({"error": f"Device did not respond: {e}"}, status=504)
    except Exception as e:
        log.exception("Unhandled error on %s %s", request.method, request.path)
        return web.json_response({"error": str(e)}, status=500)


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise BadRequest("Body must be JSON") from None
    if not isinstance(body, dict):
        raise BadRequest("Body must be a JSON object")
    return body


def _number(body: dict, key: str) -> float:
    if key not in body:
        raise BadRequest(f"Missing {key}")
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BadRequest(f"{key} must be a finite number")
    return float(value)


def _string(body: dict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise BadRequest(f"{key} must be a non-empty string")
    return value


def _ok(status: int = 200) -> web.Response:
    return web.json_response({"ok": True}, status=status)


class _Api:
    def __init__(self, engine: Engine, token: str) -> None:
        self.engine = engine
        self.token = token

    async def index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def state(self, request: web.Request) -> web.Response:
        return web.json_response(self.engine.state())

    async def library(self, request: web.Request) -> web.Response:
        return web.json_response(await self.engine.library())

    async def browse(self, request: web.Request) -> web.Response:
        folders = self.engine.config.watch_folders
        raw = request.query.get("path")
        if raw is None or raw == "":
            return web.json_response(paths.watch_roots(folders))
        target = Path(raw)
        if not paths.is_under(target, folders):
            raise Forbidden("Path is not in a watch folder")
        if not target.is_dir():
            raise NotFound("Folder not found")
        try:
            entries = await asyncio.to_thread(paths.list_folder, target)
        except PermissionError:
            raise Forbidden("Permission denied") from None
        return web.json_response(entries)

    async def get_settings(self, request: web.Request) -> web.Response:
        return web.json_response(self.engine.settings())

    async def put_settings(self, request: web.Request) -> web.Response:
        auth.require_local(request.headers.get("Authorization"), self.token)
        body = await _json_body(request)
        return web.json_response(self.engine.update_settings(body))

    async def cast(self, request: web.Request) -> web.Response:
        local = auth.is_local(request.headers.get("Authorization"), self.token)
        body = await _json_body(request)
        path = Path(_string(body, "path")).expanduser()
        resume = body.get("resume", False)
        if not isinstance(resume, bool):
            raise BadRequest("resume must be true or false")
        if not path.is_absolute():
            raise BadRequest("path must be absolute")
        if not local:
            in_folder = paths.is_under(path, self.engine.config.watch_folders)
            if not in_folder and not await self.engine.is_in_history(path):
                raise Forbidden("Path is not in a watch folder")
        if not path.is_file():
            raise NotFound("File not found")
        return web.json_response(self.engine.request_cast(path, resume), status=202)

    async def toggle(self, request: web.Request) -> web.Response:
        await self.engine.toggle_pause()
        return _ok()

    async def stop(self, request: web.Request) -> web.Response:
        await self.engine.stop()
        return _ok()

    async def seek(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        position = _number(body, "position") if "position" in body else None
        offset = _number(body, "offset") if "offset" in body else None
        await self.engine.seek(position=position, offset=offset)
        return _ok()

    async def volume(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        await self.engine.set_volume(_number(body, "level"))
        return _ok()

    async def scan(self, request: web.Request) -> web.Response:
        self.engine.request_scan()
        return _ok(status=202)

    async def select_device(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.engine.select_device(_string(body, "device_id"))
        return _ok()

    async def pin(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.engine.submit_pin(_string(body, "pin"))
        return _ok()

    async def events(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        queue = self.engine.events.subscribe()
        forwarder: asyncio.Task | None = None
        try:
            await ws.send_json({"type": "state", "data": self.engine.state()})
            forwarder = asyncio.create_task(self._forward(queue, ws))
            async for _ in ws:
                pass  # clients send commands over HTTP; the socket only pushes
        finally:
            if forwarder is not None:
                forwarder.cancel()
            self.engine.events.unsubscribe(queue)
        return ws

    @staticmethod
    async def _forward(queue: asyncio.Queue, ws: web.WebSocketResponse) -> None:
        while True:
            event = await queue.get()
            await ws.send_json(event)


def create_app(engine: Engine, token: str) -> web.Application:
    api = _Api(engine, token)
    app = web.Application(middlewares=[_error_middleware])
    r = app.router
    r.add_get("/", api.index)
    r.add_get("/api/state", api.state)
    r.add_get("/api/library", api.library)
    r.add_get("/api/browse", api.browse)
    r.add_get("/api/settings", api.get_settings)
    r.add_put("/api/settings", api.put_settings)
    r.add_post("/api/cast", api.cast)
    r.add_post("/api/playback/toggle", api.toggle)
    r.add_post("/api/playback/stop", api.stop)
    r.add_post("/api/playback/seek", api.seek)
    r.add_post("/api/playback/volume", api.volume)
    r.add_post("/api/devices/scan", api.scan)
    r.add_post("/api/devices/select", api.select_device)
    r.add_post("/api/pairing/pin", api.pin)
    r.add_get("/api/events", api.events)
    return app

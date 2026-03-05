"""aiohttp media server with Range request support and transcoded stream serving."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from pathlib import Path
from typing import AsyncIterator

from aiohttp import web

from video_caster.utils.network import get_local_ip, get_local_ip_for

log = logging.getLogger(__name__)


class MediaServer:
    def __init__(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/file/{file_id}", self._handle_file)
        self._app.router.add_get("/stream/{stream_id}", self._handle_stream)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._files: dict[str, Path] = {}
        self._streams: dict[str, AsyncIterator[bytes]] = {}
        self._port = 0

    @property
    def base_url(self) -> str:
        return f"http://{get_local_ip()}:{self._port}"

    def base_url_for(self, device_ip: str) -> str:
        """Get a base URL reachable from the given device IP."""
        local_ip = get_local_ip_for(device_ip)
        return f"http://{local_ip}:{self._port}"

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", 0)
        await self._site.start()
        # Extract actual bound port
        sockets = self._site._server.sockets  # type: ignore[union-attr]
        self._port = sockets[0].getsockname()[1]
        log.info("Media server listening on %s", self.base_url)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    def register_file(self, file_id: str, path: Path, device_ip: str = "") -> str:
        self._files[file_id] = path
        base = self.base_url_for(device_ip) if device_ip else self.base_url
        return f"{base}/file/{file_id}"

    def register_stream(self, stream_id: str, stream: AsyncIterator[bytes], device_ip: str = "") -> str:
        self._streams[stream_id] = stream
        base = self.base_url_for(device_ip) if device_ip else self.base_url
        return f"{base}/stream/{stream_id}"

    def unregister_stream(self, stream_id: str) -> None:
        self._streams.pop(stream_id, None)

    async def _handle_file(self, request: web.Request) -> web.StreamResponse:
        file_id = request.match_info["file_id"]
        path = self._files.get(file_id)
        if path is None or not path.exists():
            raise web.HTTPNotFound()

        file_size = path.stat().st_size
        content_type = mimetypes.guess_type(str(path))[0] or "video/mp4"

        range_header = request.headers.get("Range")
        if range_header:
            return await self._serve_range(request, path, file_size, content_type, range_header)

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": content_type,
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            },
        )
        await response.prepare(request)

        with open(path, "rb") as f:
            while chunk := f.read(64 * 1024):
                await response.write(chunk)
                await asyncio.sleep(0)  # yield to event loop

        return response

    async def _serve_range(
        self,
        request: web.Request,
        path: Path,
        file_size: int,
        content_type: str,
        range_header: str,
    ) -> web.StreamResponse:
        try:
            range_spec = range_header.replace("bytes=", "")
            start_str, end_str = range_spec.split("-", 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
        except (ValueError, IndexError):
            raise web.HTTPRequestRangeNotSatisfiable(
                headers={"Content-Range": f"bytes */{file_size}"}
            )

        if start >= file_size or end >= file_size:
            raise web.HTTPRequestRangeNotSatisfiable(
                headers={"Content-Range": f"bytes */{file_size}"}
            )

        content_length = end - start + 1
        response = web.StreamResponse(
            status=206,
            headers={
                "Content-Type": content_type,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
            },
        )
        await response.prepare(request)

        with open(path, "rb") as f:
            f.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk_size = min(64 * 1024, remaining)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                await response.write(chunk)
                remaining -= len(chunk)
                await asyncio.sleep(0)

        return response

    async def _handle_stream(self, request: web.Request) -> web.StreamResponse:
        stream_id = request.match_info["stream_id"]
        stream = self._streams.get(stream_id)
        if stream is None:
            raise web.HTTPNotFound()

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "video/mp4",
                "Transfer-Encoding": "chunked",
            },
        )
        await response.prepare(request)

        try:
            async for chunk in stream:
                await response.write(chunk)
        except (ConnectionResetError, asyncio.CancelledError):
            log.debug("Stream client disconnected for %s", stream_id)
        finally:
            self._streams.pop(stream_id, None)

        return response

"""aiohttp media server with Range request support and transcoded stream serving."""

from __future__ import annotations

import asyncio
import logging
import math
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from aiohttp import web

from video_caster.transcoding.hls import HLS_SEGMENT_DURATION, segments_for_duration
from video_caster.utils.network import get_local_ip, get_local_ip_for

log = logging.getLogger(__name__)


# Async callback: (stream_id, segment_index) -> None.
# Orchestrator implements this to restart ffmpeg at a new offset when the
# receiver requests a segment too far ahead of the current encode position.
EnsureSegmentCallback = Callable[[str, int], Awaitable[None]]


@dataclass
class HLSSession:
    output_dir: Path
    duration: float
    segment_duration: float = HLS_SEGMENT_DURATION
    # Per-segment durations when video is `-c:v copy` and segments align to
    # source keyframes (irregular). When set, the synthesized playlist uses
    # these EXTINF values directly. None → uniform-cadence synthesis.
    segments: list[float] | None = None
    ensure_segment: EnsureSegmentCallback | None = None
    # Lock to prevent multiple concurrent restarts for the same session.
    _restart_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class MediaServer:
    def __init__(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/file/{file_id}", self._handle_file)
        self._app.router.add_get("/stream/{stream_id}", self._handle_stream)
        self._app.router.add_get(
            "/hls/{stream_id}/playlist.m3u8", self._handle_hls_playlist
        )
        self._app.router.add_get(
            "/hls/{stream_id}/{segment}", self._handle_hls_segment
        )
        # The Chromecast receiver fetches HLS playlists and segments via XHR,
        # so without CORS headers it silently discards every response and
        # reports LOAD_FAILED. Plain <video src> file casts never needed this.
        self._app.router.add_route("OPTIONS", "/{tail:.*}", self._handle_preflight)
        self._app.on_response_prepare.append(self._add_cors_headers)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._files: dict[str, Path] = {}
        self._streams: dict[str, AsyncIterator[bytes]] = {}
        self._hls: dict[str, HLSSession] = {}
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

    def register_hls(
        self,
        stream_id: str,
        output_dir: Path,
        duration: float,
        ensure_segment: EnsureSegmentCallback | None,
        segment_duration: float = HLS_SEGMENT_DURATION,
        segments: list[float] | None = None,
        device_ip: str = "",
    ) -> str:
        self._hls[stream_id] = HLSSession(
            output_dir=output_dir,
            duration=duration,
            segment_duration=segment_duration,
            segments=segments,
            ensure_segment=ensure_segment,
        )
        base = self.base_url_for(device_ip) if device_ip else self.base_url
        return f"{base}/hls/{stream_id}/playlist.m3u8"

    def unregister_hls(self, stream_id: str) -> None:
        self._hls.pop(stream_id, None)

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

    @staticmethod
    async def _add_cors_headers(
        request: web.Request, response: web.StreamResponse
    ) -> None:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Range, Content-Type"
        response.headers["Access-Control-Expose-Headers"] = (
            "Content-Length, Content-Range, Accept-Ranges"
        )

    async def _handle_preflight(self, request: web.Request) -> web.Response:
        return web.Response(status=204)

    async def _handle_hls_playlist(self, request: web.Request) -> web.Response:
        stream_id = request.match_info["stream_id"]
        session = self._hls.get(stream_id)
        if session is None:
            raise web.HTTPNotFound()

        if session.segments:
            extinfs = session.segments
            target_dur = max(extinfs) if extinfs else HLS_SEGMENT_DURATION
        else:
            seg_dur = (
                session.segment_duration
                if session.segment_duration > 0
                else HLS_SEGMENT_DURATION
            )
            if session.duration <= 0:
                extinfs = []
                target_dur = seg_dur
            else:
                full_seg_count = int(session.duration // seg_dur)
                remainder = session.duration - full_seg_count * seg_dur
                extinfs = [seg_dur] * full_seg_count
                if remainder > 0:
                    extinfs.append(remainder)
                target_dur = seg_dur

        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{int(math.ceil(target_dur))}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
            "#EXT-X-INDEPENDENT-SEGMENTS",
        ]
        for i, extinf in enumerate(extinfs):
            lines.append(f"#EXTINF:{extinf:.6f},")
            lines.append(f"seg-{i:05d}.ts")
        lines.append("#EXT-X-ENDLIST")
        body = "\n".join(lines) + "\n"
        return web.Response(
            body=body.encode("utf-8"),
            content_type="application/vnd.apple.mpegurl",
        )

    async def _handle_hls_segment(self, request: web.Request) -> web.StreamResponse:
        stream_id = request.match_info["stream_id"]
        seg_name = request.match_info["segment"]
        session = self._hls.get(stream_id)
        if session is None:
            raise web.HTTPNotFound()

        # Parse seg-NNNNN.ts
        if not seg_name.startswith("seg-") or not seg_name.endswith(".ts"):
            raise web.HTTPNotFound()
        try:
            seg_index = int(seg_name[4:-3])
        except ValueError:
            raise web.HTTPNotFound()

        seg_path = session.output_dir / seg_name

        # If the segment isn't present yet, give ffmpeg a brief grace period
        # before deciding it's a far-seek that needs an ffmpeg restart.
        await self._wait_for_segment(seg_path, timeout=2.0)

        if not seg_path.exists() and session.ensure_segment is not None:
            log.info(
                "HLS seg %d not yet encoded — asking orchestrator to restart at offset",
                seg_index,
            )
            async with session._restart_lock:
                # Double-check inside lock — another request may have already triggered restart.
                if not seg_path.exists():
                    try:
                        await session.ensure_segment(stream_id, seg_index)
                    except Exception:
                        log.exception("ensure_segment failed for %d", seg_index)
            # Wait again now that ffmpeg should be encoding from the new offset.
            await self._wait_for_segment(seg_path, timeout=30.0)

        if not seg_path.exists():
            log.warning("HLS segment %s never appeared", seg_path)
            raise web.HTTPNotFound()

        # Serve the file. Range support not needed — segments are small.
        return web.FileResponse(seg_path, headers={"Content-Type": "video/mp2t"})

    async def _wait_for_segment(self, path: Path, timeout: float) -> None:
        elapsed = 0.0
        while elapsed < timeout:
            if path.exists() and path.stat().st_size > 0:
                return
            await asyncio.sleep(0.1)
            elapsed += 0.1

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

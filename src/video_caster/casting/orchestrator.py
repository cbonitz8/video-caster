"""Coordinates file probing, transcoding, serving, and casting."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from video_caster.casting.airplay import AirPlayHandler
from video_caster.casting.base import CastHandler, PlaybackStatus
from video_caster.casting.chromecast import ChromecastHandler
from video_caster.casting.dlna import DLNAHandler
from video_caster.discovery.device import Device, DeviceType
from video_caster.server.media_server import MediaServer
from video_caster.transcoding.formats import needs_transcode
from video_caster.transcoding.probe import ProbeResult, probe
from video_caster.transcoding.transcoder import Transcoder

log = logging.getLogger(__name__)


class CastOrchestrator:
    def __init__(self) -> None:
        self.server = MediaServer()
        self._transcoder = Transcoder()
        self._handler: CastHandler | None = None
        self._current_device: Device | None = None
        self._current_stream_id: str | None = None
        self.pin_callback = None  # async fn(device_name, protocol) -> str, set by UI

    async def start(self) -> None:
        await self.server.start()

    async def stop(self) -> None:
        await self.stop_playback()
        await self.server.stop()

    async def connect_device(self, device: Device) -> CastHandler:
        if self._handler:
            await self._handler.disconnect()

        if device.device_type == DeviceType.CHROMECAST:
            handler = ChromecastHandler(device)
        elif device.device_type == DeviceType.DLNA:
            handler = DLNAHandler(device)
        else:
            handler = AirPlayHandler(device)

        await handler.connect()
        self._handler = handler
        self._current_device = device
        return handler

    async def _ensure_airplay_paired(self, device: Device) -> None:
        """Pair with Apple TV if not already authenticated."""
        if device.device_type != DeviceType.APPLETV:
            return
        if not self.pin_callback:
            raise RuntimeError("No PIN callback set — cannot pair with Apple TV")

        handler = AirPlayHandler(device)
        await handler.pair(self.pin_callback)

        # Reconnect with new credentials
        if self._handler:
            await self._handler.disconnect()
        handler2 = AirPlayHandler(device)
        await handler2.connect()
        self._handler = handler2
        self._current_device = device

    async def cast_file(self, file_path: Path, device: Device) -> None:
        """Probe, transcode if needed, serve, and cast a file."""
        log.info("Casting %s to %s", file_path.name, device.name)

        # Connect if needed
        if self._current_device != device or self._handler is None:
            await self.connect_device(device)

        # Stop any current playback
        await self.stop_playback()

        # Probe file
        probe_result = await probe(file_path)
        if not probe_result.video_codec:
            raise RuntimeError(f"Could not probe {file_path.name}")

        target = device.device_type.value
        need_video, need_audio, need_remux = needs_transcode(
            probe_result.video_codec,
            probe_result.audio_codec,
            probe_result.container,
            target,
        )

        title = file_path.stem
        duration = probe_result.duration

        # All devices use HTTP: Chromecast fetches from our server,
        # AirPlay devices use play_url to fetch from our server.
        if need_video or need_audio or need_remux:
            url = await self._serve_transcoded(file_path, need_video, need_audio, device.address)
            log.info("Serving transcoded stream at %s", url)
        else:
            file_id = str(uuid.uuid4())
            url = self.server.register_file(file_id, file_path, device.address)
            log.info("Serving file directly at %s", url)
        await self._play_with_auth_retry(device, url=url, title=title, duration=duration)



    async def _play_with_auth_retry(
        self,
        device: Device,
        *,
        url: str,
        title: str = "",
        duration: float = 0.0,
    ) -> None:
        """Play media, retrying with pairing if auth fails (Apple TV)."""
        try:
            await self._do_play(url, title=title, duration=duration)
        except Exception as e:
            err_msg = str(e).lower()
            if any(kw in err_msg for kw in ("auth", "credentials", "not_permitted", "forbidden", "not implemented")):
                log.info("Auth/protocol failed, attempting pairing for %s", device.name)
                await self._ensure_airplay_paired(device)
                await self._do_play(url, title=title, duration=duration)
            else:
                raise

    async def _do_play(self, url: str, *, title: str = "", duration: float = 0.0) -> None:
        """Send play command to the current handler."""
        if isinstance(self._handler, ChromecastHandler):
            await self._handler.play_media(url, title=title, duration=duration)
        elif isinstance(self._handler, DLNAHandler):
            await self._handler.play_media(url)
        else:
            await self._handler.play_media(url)

    async def _serve_transcoded(
        self, path: Path, transcode_video: bool, transcode_audio: bool, device_ip: str = ""
    ) -> str:
        stream = await self._transcoder.start(
            path,
            transcode_video=transcode_video,
            transcode_audio=transcode_audio,
        )
        stream_id = str(uuid.uuid4())
        self._current_stream_id = stream_id
        return self.server.register_stream(stream_id, stream, device_ip)

    async def stop_playback(self) -> None:
        if self._handler:
            try:
                await self._handler.stop()
            except Exception:
                pass

        await self._transcoder.stop()

        if self._current_stream_id:
            self.server.unregister_stream(self._current_stream_id)
            self._current_stream_id = None

    async def pause(self) -> None:
        if self._handler:
            await self._handler.pause()

    async def resume(self) -> None:
        if self._handler:
            await self._handler.resume()

    async def toggle_pause(self) -> None:
        if self._handler:
            status = await self._handler.get_status()
            if status.state == "playing":
                await self._handler.pause()
            else:
                await self._handler.resume()

    async def seek(self, position: float) -> None:
        if self._handler:
            await self._handler.seek(position)

    async def set_volume(self, level: float) -> None:
        if self._handler:
            await self._handler.set_volume(max(0.0, min(1.0, level)))

    async def get_status(self) -> PlaybackStatus:
        if self._handler:
            return await self._handler.get_status()
        return PlaybackStatus()

    async def disconnect(self) -> None:
        await self.stop_playback()
        if self._handler:
            await self._handler.disconnect()
            self._handler = None
            self._current_device = None


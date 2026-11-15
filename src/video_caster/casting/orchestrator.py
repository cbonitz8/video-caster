"""Coordinates file probing, transcoding, serving, and casting."""

from __future__ import annotations

import logging
from pathlib import Path

from pychromecast.error import RequestTimeout

from video_caster.casting.base import (
    CastSession,
    OpenSession,
    PlaybackStatus,
    RequestPin,
    StopFailed,
)
from video_caster.casting.stream_plan import (
    OpenStream,
    Stream,
    capabilities_for,
    choose_plan,
    open_stream,
)
from video_caster.discovery.device import Device
from video_caster.server.media_server import MediaServer
from video_caster.transcoding.probe import probe

log = logging.getLogger(__name__)


class CastOrchestrator:
    def __init__(self, open_session: OpenSession, open_stream: OpenStream = open_stream) -> None:
        self.server = MediaServer()
        self._open_session = open_session
        self._open_stream = open_stream
        self._session: CastSession | None = None
        self._stream: Stream | None = None

    async def start(self) -> None:
        await self.server.start()

    async def stop(self) -> None:
        await self._end_playback_quietly()
        if self._session is not None:
            session, self._session = self._session, None
            await session.close()
        await self.server.stop()

    async def _switch_to(self, device: Device, request_pin: RequestPin) -> None:
        old, self._session = self._session, None
        if old is not None:
            try:
                await old.stop()
            except Exception:
                log.warning("Couldn't stop %s before switching", old.device.name, exc_info=True)
            try:
                await old.close()
            except Exception:
                log.warning("Couldn't close %s before switching", old.device.name, exc_info=True)
        self._session = await self._open_session(device, request_pin)

    async def cast_file(self, file_path: Path, device: Device, request_pin: RequestPin) -> None:
        """Probe, choose a stream plan, serve, and cast a file."""
        log.info("Casting %s to %s", file_path.name, device.name)

        if self._session is None or self._session.device.id != device.id:
            await self._switch_to(device, request_pin)

        await self._end_playback_quietly()

        probed = await probe(file_path)
        if not probed.video_codec:
            raise RuntimeError(f"Could not probe {file_path.name}")

        plan = choose_plan(probed, capabilities_for(device.device_type))
        self._stream = await self._open_stream(plan, file_path, probed, self.server, device.address)
        await self._session.play(self._stream.media)

    async def _end_playback_quietly(self) -> None:
        try:
            await self.stop_playback()
        except Exception:
            log.warning("Couldn't stop the previous playback", exc_info=True)

    async def stop_playback(self) -> None:
        """Stop the device, then tear the stream down. A device error reaches the caller after teardown."""
        stream, self._stream = self._stream, None
        try:
            if self._session is not None:
                await _stop_device(self._session)
        finally:
            if stream is not None:
                await stream.teardown()

    async def toggle_pause(self) -> None:
        if self._session:
            status = await self._session.get_status()
            if status.state == "playing":
                await self._session.pause()
            else:
                await self._session.resume()

    async def seek(self, position: float) -> None:
        if self._session is None or self._stream is None:
            return
        await self._stream.seek(self._session, position)

    async def set_volume(self, level: float) -> None:
        if self._session:
            await self._session.set_volume(max(0.0, min(1.0, level)))

    async def get_status(self) -> PlaybackStatus:
        if self._session:
            return await self._session.get_status()
        return PlaybackStatus()


async def _stop_device(session: CastSession) -> None:
    try:
        await session.stop()
    except (TimeoutError, RequestTimeout):
        raise
    except Exception as e:
        raise StopFailed(f"{session.device.name} didn't stop: {e}") from e

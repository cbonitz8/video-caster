"""pychromecast wrapper with async bridging."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pychromecast
from pychromecast.config import APP_MEDIA_RECEIVER
from pychromecast.error import PyChromecastError, RequestTimeout

from video_caster.casting.base import CastSession, Media, PlaybackStatus, device_request
from video_caster.discovery.device import Device

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chromecast")


async def _run_sync(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(_executor, fn, *args)


async def open_chromecast(device: Device) -> ChromecastSession:
    log.info("Connecting to Chromecast: %s", device.name)
    # A disconnected Chromecast's socket thread cannot be restarted, so each
    # session builds its own object.
    cast = pychromecast.get_chromecast_from_host(
        (device.address, device.port, UUID(device.id), device.model, device.name)
    )
    await _run_sync(cast.wait)
    log.info("Connected to Chromecast: %s", device.name)
    return ChromecastSession(device, cast)


class ChromecastSession(CastSession):
    def __init__(self, device: Device, cast: pychromecast.Chromecast) -> None:
        super().__init__(device)
        self._cast = cast

    async def close(self) -> None:
        await _run_sync(self._cast.disconnect)

    async def play(self, media: Media) -> None:
        mc = self._cast.media_controller

        def _play():
            # MediaController sends LOAD to any foreground app that speaks the
            # media namespace (e.g. Spotify), which ignores it.
            self._cast.start_app(APP_MEDIA_RECEIVER)
            mc.play_media(
                media.url,
                media.content_type,
                title=media.title or None,
                stream_type="BUFFERED",
                metadata={"title": media.title} if media.title else None,
                media_info={"duration": media.duration} if media.duration > 0 else None,
            )
            mc.block_until_active(timeout=10)

        await _run_sync(_play)

    async def _request(self, action: str, fn, *args) -> None:
        with device_request(self.device, action, timeouts=(RequestTimeout,), failures=(PyChromecastError,)):
            await _run_sync(fn, *args)

    async def pause(self) -> None:
        await self._request("pause", self._cast.media_controller.pause)

    async def resume(self) -> None:
        await self._request("resume", self._cast.media_controller.play)

    async def stop(self) -> None:
        await self._request("stop", self._cast.media_controller.stop)

    async def seek(self, position: float) -> None:
        await self._request("seek", self._cast.media_controller.seek, position)

    async def set_volume(self, level: float) -> None:
        await self._request("change volume", self._cast.set_volume, level)

    async def get_status(self) -> PlaybackStatus:
        def _get():
            ms = self._cast.media_controller.status
            return PlaybackStatus(
                state=ms.player_state.lower() if ms.player_state else "idle",
                current_time=ms.adjusted_current_time or ms.current_time or 0.0,
                duration=ms.duration or 0.0,
                volume=self._cast.status.volume_level if self._cast.status else 1.0,
            )

        return await _run_sync(_get)

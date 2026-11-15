"""pychromecast wrapper with async bridging."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pychromecast
from pychromecast.config import APP_MEDIA_RECEIVER
from pychromecast.controllers.media import MediaStatusListener

from video_caster.casting.base import CastHandler, PlaybackStatus
from video_caster.discovery.device import Device

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chromecast")


class ChromecastHandler(CastHandler):
    def __init__(self, device: Device) -> None:
        super().__init__(device)
        self._cast: pychromecast.Chromecast | None = None
        self._status = PlaybackStatus()

    async def _run_sync(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, fn, *args)

    async def connect(self) -> None:
        log.info("Connecting to Chromecast: %s", self.device.name)
        browser = self.device.protocol_config.get("browser")
        discovered = self.device.protocol_config.get("cast")

        if discovered is None or browser is None:
            raise RuntimeError(f"No cast object for {self.device.name}")

        # A disconnected Chromecast's socket thread cannot be restarted, so each
        # connection gets its own object rather than reusing the discovered one.
        self._cast = pychromecast.get_chromecast_from_cast_info(
            discovered.cast_info, browser.zc
        )
        await self._run_sync(self._cast.wait)
        log.info("Connected to Chromecast: %s", self.device.name)

    async def disconnect(self) -> None:
        if self._cast:
            await self._run_sync(self._cast.disconnect)
            self._cast = None

    async def play_media(
        self,
        url: str,
        content_type: str = "video/mp4",
        *,
        title: str = "",
        duration: float = 0.0,
    ) -> None:
        if not self._cast:
            raise RuntimeError("Not connected")
        mc = self._cast.media_controller

        metadata = {}
        if title:
            metadata["title"] = title

        media_info: dict = {}
        if duration > 0:
            media_info["duration"] = duration

        def _play():
            # MediaController sends LOAD to any foreground app that speaks the
            # media namespace (e.g. Spotify), which ignores it.
            self._cast.start_app(APP_MEDIA_RECEIVER)
            mc.play_media(
                url,
                content_type,
                title=title or None,
                stream_type="BUFFERED",
                metadata=metadata if metadata else None,
                media_info=media_info or None,
            )
            mc.block_until_active(timeout=10)

        await self._run_sync(_play)

    async def pause(self) -> None:
        if self._cast:
            await self._run_sync(self._cast.media_controller.pause)

    async def resume(self) -> None:
        if self._cast:
            await self._run_sync(self._cast.media_controller.play)

    async def stop(self) -> None:
        if self._cast:
            await self._run_sync(self._cast.media_controller.stop)

    async def seek(self, position: float) -> None:
        if self._cast:
            await self._run_sync(self._cast.media_controller.seek, position)

    async def set_volume(self, level: float) -> None:
        if self._cast:
            await self._run_sync(self._cast.set_volume, level)

    async def get_status(self) -> PlaybackStatus:
        if not self._cast:
            return PlaybackStatus()

        def _get():
            ms = self._cast.media_controller.status
            return PlaybackStatus(
                state=ms.player_state.lower() if ms.player_state else "idle",
                current_time=ms.adjusted_current_time or ms.current_time or 0.0,
                duration=ms.duration or 0.0,
                volume=self._cast.status.volume_level if self._cast.status else 1.0,
                title=ms.title or "",
            )

        return await self._run_sync(_get)

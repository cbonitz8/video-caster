"""pyatv AirPlay wrapper."""

from __future__ import annotations

import asyncio
import json
import logging

import pyatv
from pyatv.const import Protocol

from video_caster.casting.base import CastHandler, PlaybackStatus
from video_caster.config import CONFIG_DIR
from video_caster.discovery.device import Device

log = logging.getLogger(__name__)

CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"


def _load_credentials() -> dict[str, dict[str, str]]:
    if CREDENTIALS_PATH.exists():
        return json.loads(CREDENTIALS_PATH.read_text())
    return {}


def _save_credentials(creds: dict[str, dict[str, str]]) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(creds, indent=2))


class AirPlayHandler(CastHandler):
    def __init__(self, device: Device) -> None:
        super().__init__(device)
        self._atv: pyatv.interface.AppleTV | None = None
        self._pairing_callback = None  # set by UI for PIN input

    async def connect(self) -> None:
        log.info("Connecting to Apple TV: %s", self.device.name)
        config = self.device.protocol_config.get("config")
        if config is None:
            raise RuntimeError(f"No pyatv config for {self.device.name}")

        # Apply stored credentials
        creds = _load_credentials()
        device_creds = creds.get(self.device.id, {})
        for proto_str, credential in device_creds.items():
            try:
                proto = Protocol(int(proto_str))
                config.set_credentials(proto, credential)
            except (ValueError, KeyError):
                pass

        self._atv = await pyatv.connect(config, loop=asyncio.get_running_loop())
        log.info("Connected to Apple TV: %s", self.device.name)

    async def pair(self, pin_callback) -> bool:
        """Pair with the device. pin_callback is an async fn that returns the PIN string."""
        config = self.device.protocol_config.get("config")
        if config is None:
            return False

        for protocol in (Protocol.AirPlay, Protocol.Companion):
            try:
                pairing = await pyatv.pair(config, protocol, loop=asyncio.get_running_loop())
                await pairing.begin()

                if pairing.device_provides_pin:
                    pin = await pin_callback(self.device.name, protocol.name)
                    if pin:
                        pairing.pin(int(pin))

                await pairing.finish()

                if pairing.has_paired:
                    creds = _load_credentials()
                    device_creds = creds.setdefault(self.device.id, {})
                    device_creds[str(protocol.value)] = pairing.credentials
                    _save_credentials(creds)
                    log.info("Paired %s via %s", self.device.name, protocol.name)

                await pairing.close()
            except Exception as e:
                log.warning("Pairing failed for %s via %s: %s", self.device.name, protocol.name, e)

        return True

    async def disconnect(self) -> None:
        if self._atv:
            self._atv.close()
            self._atv = None

    async def play_media(self, url: str, content_type: str = "video/mp4") -> None:
        if not self._atv:
            raise RuntimeError("Not connected")
        log.info("play_url called with: %s", url)
        await self._atv.stream.play_url(url)

    async def pause(self) -> None:
        if self._atv:
            await self._atv.remote_control.pause()

    async def resume(self) -> None:
        if self._atv:
            await self._atv.remote_control.play()

    async def stop(self) -> None:
        if self._atv:
            await self._atv.remote_control.stop()

    async def seek(self, position: float) -> None:
        if self._atv:
            await self._atv.remote_control.set_position(int(position))

    async def set_volume(self, level: float) -> None:
        if self._atv and self._atv.audio:
            await self._atv.audio.set_volume(level * 100)

    async def get_status(self) -> PlaybackStatus:
        if not self._atv:
            return PlaybackStatus()
        try:
            playing = await self._atv.metadata.playing()
            state_map = {
                pyatv.const.DeviceState.Playing: "playing",
                pyatv.const.DeviceState.Paused: "paused",
                pyatv.const.DeviceState.Stopped: "stopped",
                pyatv.const.DeviceState.Loading: "buffering",
            }
            return PlaybackStatus(
                state=state_map.get(playing.device_state, "idle"),
                current_time=playing.position or 0.0,
                duration=playing.total_time or 0.0,
                volume=self._atv.audio.volume / 100 if self._atv.audio else 1.0,
                title=playing.title or "",
            )
        except Exception:
            return PlaybackStatus()

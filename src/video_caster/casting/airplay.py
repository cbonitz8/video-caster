"""pyatv AirPlay adapter."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pyatv
from pyatv.const import DeviceState, PairingRequirement, Protocol
from pyatv.exceptions import (
    AuthenticationError,
    BlockedStateError,
    CommandError,
    ConnectionLostError,
    NotSupportedError,
    OperationTimeoutError,
    PairingError,
    PlaybackError,
    ProtocolError,
)

from video_caster.casting.base import (
    CastSession,
    CredentialsRejected,
    Media,
    PairingFailed,
    PlaybackStatus,
    RequestPin,
    device_request,
)
from video_caster.discovery.device import Device

log = logging.getLogger(__name__)

SCAN_TIMEOUT = 5

_REQUEST_FAILURES = (ConnectionLostError, CommandError, PlaybackError, BlockedStateError, ProtocolError)

_STATE_MAP = {
    DeviceState.Playing: "playing",
    DeviceState.Paused: "paused",
    DeviceState.Stopped: "stopped",
    DeviceState.Loading: "buffering",
}


def _load_credentials(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_credential(path: Path, device_id: str, credential: str) -> None:
    creds = _load_credentials(path)
    creds[device_id] = credential
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(creds, indent=2))


def _forget_credential(path: Path, device_id: str) -> None:
    creds = _load_credentials(path)
    if creds.pop(device_id, None) is not None:
        path.write_text(json.dumps(creds, indent=2))


def _rejected(device: Device, credentials_path: Path, error: Exception) -> CredentialsRejected:
    _forget_credential(credentials_path, device.id)
    log.warning("%s rejected its stored credential: %s", device.name, error)
    return CredentialsRejected(
        f"{device.name} rejected the saved pairing. Cast again to pair with a new PIN."
    )


async def _pair(config, device: Device, request_pin: RequestPin, pyatv) -> str:
    pairing = await pyatv.pair(config, Protocol.AirPlay, loop=asyncio.get_running_loop())
    try:
        await pairing.begin()
        if pairing.device_provides_pin:
            pin = await request_pin(device.name)
            if not pin.isdigit():
                raise PairingFailed(f"PIN for {device.name} must be digits")
            pairing.pin(int(pin))
        await pairing.finish()
    except (PairingError, AuthenticationError) as e:
        raise PairingFailed(f"Pairing with {device.name} failed: {e}") from e
    finally:
        await pairing.close()
    if not pairing.has_paired:
        raise PairingFailed(f"Pairing with {device.name} failed")
    log.info("Paired %s via AirPlay", device.name)
    return pairing.credentials


async def open_airplay(
    device: Device,
    request_pin: RequestPin,
    *,
    credentials_path: Path,
    pyatv=pyatv,
) -> AirPlaySession:
    log.info("Connecting to Apple TV: %s", device.name)
    loop = asyncio.get_running_loop()
    configs = await pyatv.scan(
        loop, identifier=device.id, hosts=[device.address], timeout=SCAN_TIMEOUT
    )
    if not configs:
        raise RuntimeError(f"{device.name} did not answer at {device.address}")
    config = configs[0]

    service = config.get_service(Protocol.AirPlay)
    if service is None:
        raise RuntimeError(f"{device.name} does not offer AirPlay")

    credential = _load_credentials(credentials_path).get(device.id)
    if credential is None and service.pairing == PairingRequirement.Mandatory:
        credential = await _pair(config, device, request_pin, pyatv)
        _save_credential(credentials_path, device.id, credential)
    if credential is not None:
        config.set_credentials(Protocol.AirPlay, credential)

    try:
        atv = await pyatv.connect(config, loop=loop)
    except AuthenticationError as e:
        raise _rejected(device, credentials_path, e) from e
    log.info("Connected to Apple TV: %s", device.name)
    return AirPlaySession(device, atv, credentials_path)


class AirPlaySession(CastSession):
    def __init__(self, device: Device, atv, credentials_path: Path) -> None:
        super().__init__(device)
        self._atv = atv
        self._credentials_path = credentials_path

    async def close(self) -> None:
        self._atv.close()

    async def play(self, media: Media) -> None:
        log.info("play_url called with: %s", media.url)
        try:
            await self._atv.stream.play_url(media.url)
        except AuthenticationError as e:
            raise _rejected(self.device, self._credentials_path, e) from e

    def _request(self, action: str):
        return device_request(
            self.device, action, timeouts=(OperationTimeoutError,), failures=_REQUEST_FAILURES
        )

    async def pause(self) -> None:
        with self._request("pause"):
            await self._atv.remote_control.pause()

    async def resume(self) -> None:
        with self._request("resume"):
            await self._atv.remote_control.play()

    async def stop(self) -> None:
        with self._request("stop"):
            await self._atv.remote_control.stop()

    async def seek(self, position: float) -> None:
        with self._request("seek"):
            await self._atv.remote_control.set_position(int(position))

    async def set_volume(self, level: float) -> None:
        if self._atv.audio:
            with self._request("change volume"):
                await self._atv.audio.set_volume(level * 100)

    async def get_status(self) -> PlaybackStatus:
        with self._request("report status"):
            playing = await self._atv.metadata.playing()
        return PlaybackStatus(
            state=_STATE_MAP.get(playing.device_state, "idle"),
            current_time=playing.position or 0.0,
            duration=playing.total_time or 0.0,
            volume=self._volume(),
            title=playing.title or "",
        )

    def _volume(self) -> float:
        try:
            return self._atv.audio.volume / 100
        except NotSupportedError:
            return 1.0

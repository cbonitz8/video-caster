from __future__ import annotations

from pathlib import Path

from video_caster.casting.airplay import open_airplay
from video_caster.casting.base import CastSession, OpenSession, RequestPin
from video_caster.casting.chromecast import open_chromecast
from video_caster.casting.dlna import open_dlna
from video_caster.discovery.device import Device, DeviceType


def session_opener(credentials_path: Path) -> OpenSession:
    async def open_session(device: Device, request_pin: RequestPin) -> CastSession:
        if device.device_type == DeviceType.CHROMECAST:
            return await open_chromecast(device)
        if device.device_type == DeviceType.DLNA:
            return await open_dlna(device)
        return await open_airplay(device, request_pin, credentials_path=credentials_path)

    return open_session

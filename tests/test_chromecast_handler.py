from __future__ import annotations

from pychromecast.config import APP_MEDIA_RECEIVER

from video_caster.casting.chromecast import ChromecastHandler
from video_caster.discovery.device import Device, DeviceType


class FakeMediaController:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def play_media(self, url, content_type, **kwargs) -> None:
        self._calls.append(f"load:{url}")

    def block_until_active(self, timeout=None) -> None:
        self._calls.append("block")


class FakeCast:
    def __init__(self, app_id: str | None) -> None:
        self.app_id = app_id
        self.calls: list[str] = []
        self.media_controller = FakeMediaController(self.calls)

    def start_app(self, app_id: str, force_launch: bool = False, timeout: float = 10) -> None:
        self.calls.append(f"start:{app_id}")
        self.app_id = app_id


def handler_for(cast: FakeCast) -> ChromecastHandler:
    device = Device(
        name="Living Room",
        device_type=DeviceType.CHROMECAST,
        address="192.0.2.1",
        protocol_config={"cast": cast},
    )
    handler = ChromecastHandler(device)
    handler._cast = cast
    return handler


async def test_play_media_takes_over_from_another_app():
    cast = FakeCast(app_id="Spotify")

    await handler_for(cast).play_media("http://host/playlist.m3u8")

    assert cast.calls[0] == f"start:{APP_MEDIA_RECEIVER}"
    assert cast.calls[1] == "load:http://host/playlist.m3u8"

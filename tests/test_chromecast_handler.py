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


class FakeSocketCast:
    def __init__(self) -> None:
        self.cast_info = object()
        self.started = False
        self.stopped = False

    def wait(self, timeout=None) -> None:
        if self.started:
            raise RuntimeError("threads can only be started once")
        self.started = True

    def disconnect(self, timeout=None) -> None:
        self.stopped = True


class FakeBrowser:
    zc = object()


async def test_reconnect_after_disconnect_uses_fresh_cast(monkeypatch):
    discovered = FakeSocketCast()
    built: list[FakeSocketCast] = []

    def build(cast_info, zconf):
        assert cast_info is discovered.cast_info
        assert zconf is FakeBrowser.zc
        cast = FakeSocketCast()
        built.append(cast)
        return cast

    monkeypatch.setattr(
        "video_caster.casting.chromecast.pychromecast.get_chromecast_from_cast_info", build
    )
    device = Device(
        name="Living Room",
        device_type=DeviceType.CHROMECAST,
        address="192.0.2.1",
        protocol_config={"cast": discovered, "browser": FakeBrowser()},
    )

    first = ChromecastHandler(device)
    await first.connect()
    await first.disconnect()
    await ChromecastHandler(device).connect()

    assert len(built) == 2
    assert built[0].stopped
    assert built[1].started

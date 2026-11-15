from __future__ import annotations

from uuid import UUID

from pychromecast.config import APP_MEDIA_RECEIVER

from video_caster.casting.base import Media
from video_caster.casting.chromecast import ChromecastSession, open_chromecast
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


LIVING_ROOM = Device(
    id="5a7c8bd4-1f2e-4c3b-9a8d-7e6f5a4b3c2d",
    name="Living Room",
    device_type=DeviceType.CHROMECAST,
    address="192.0.2.1",
    port=8009,
    model="Chromecast",
)


async def test_play_takes_over_from_another_app():
    cast = FakeCast(app_id="Spotify")

    await ChromecastSession(LIVING_ROOM, cast).play(
        Media(url="http://host/playlist.m3u8", content_type="application/vnd.apple.mpegurl",
              title="Show", duration=60.0)
    )

    assert cast.calls[0] == f"start:{APP_MEDIA_RECEIVER}"
    assert cast.calls[1] == "load:http://host/playlist.m3u8"


class FakeSocketCast:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def wait(self, timeout=None) -> None:
        if self.started:
            raise RuntimeError("threads can only be started once")
        self.started = True

    def disconnect(self, timeout=None) -> None:
        self.stopped = True


async def test_reopen_after_close_uses_a_fresh_cast(monkeypatch):
    built: list[FakeSocketCast] = []

    def build(host):
        assert host == ("192.0.2.1", 8009, UUID(LIVING_ROOM.id), "Chromecast", "Living Room")
        cast = FakeSocketCast()
        built.append(cast)
        return cast

    monkeypatch.setattr(
        "video_caster.casting.chromecast.pychromecast.get_chromecast_from_host", build
    )

    first = await open_chromecast(LIVING_ROOM)
    await first.close()
    await open_chromecast(LIVING_ROOM)

    assert len(built) == 2
    assert built[0].stopped
    assert built[1].started

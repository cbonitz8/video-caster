from __future__ import annotations

from uuid import UUID

import pytest
from pychromecast.config import APP_MEDIA_RECEIVER
from pychromecast.error import RequestFailed, RequestTimeout

from video_caster.casting.base import DeviceRequestFailed, Media
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


class RefusingMediaController:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def _refuse(self, *args) -> None:
        raise self.error

    pause = play = stop = seek = _refuse


class RefusingCast:
    def __init__(self, error: Exception) -> None:
        self.media_controller = RefusingMediaController(error)
        self.set_volume = self.media_controller._refuse


CONTROLS = [
    ("pause", (), "pause"),
    ("resume", (), "resume"),
    ("stop", (), "stop"),
    ("seek", (12.0,), "seek"),
    ("set_volume", (0.5,), "change volume"),
]


@pytest.mark.parametrize("method, args, action", CONTROLS)
async def test_a_refused_request_is_a_device_request_failure(method, args, action):
    session = ChromecastSession(LIVING_ROOM, RefusingCast(RequestFailed("play")))
    with pytest.raises(DeviceRequestFailed, match=f"Living Room didn't {action}: Failed to execute play"):
        await getattr(session, method)(*args)


@pytest.mark.parametrize("method, args, action", CONTROLS)
async def test_a_request_timeout_is_a_plain_timeout(method, args, action):
    session = ChromecastSession(LIVING_ROOM, RefusingCast(RequestTimeout("pause", 10.0)))
    with pytest.raises(TimeoutError, match=f"Living Room didn't answer {action}"):
        await getattr(session, method)(*args)


class SilentCast:
    def __init__(self) -> None:
        self.waited_for: float | None = None
        self.disconnect_timeout: float | None = None

    def wait(self, timeout=None) -> None:
        self.waited_for = timeout
        raise RequestTimeout("wait", timeout)

    def disconnect(self, timeout=None) -> None:
        self.disconnect_timeout = timeout


async def test_a_chromecast_that_never_answers_times_out_and_stops_retrying(monkeypatch):
    silent = SilentCast()
    monkeypatch.setattr(
        "video_caster.casting.chromecast.pychromecast.get_chromecast_from_host", lambda host: silent
    )

    with pytest.raises(TimeoutError, match="Living Room didn't answer within 10s"):
        await open_chromecast(LIVING_ROOM)

    assert silent.waited_for == 10.0
    assert silent.disconnect_timeout == 0

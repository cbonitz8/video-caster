from __future__ import annotations

import shutil
import subprocess

import pytest

from video_caster.casting.base import (
    CastSession, DeviceRequestFailed, Media, PairingFailed, PlaybackStatus,
)
from video_caster.casting.orchestrator import CastOrchestrator
from video_caster.casting.stream_plan import Direct, Pipe, Stream
from video_caster.discovery.device import Device, DeviceType

TV = Device(id="cc-uuid", name="Living Room", device_type=DeviceType.CHROMECAST,
            address="127.0.0.2", port=8009)
DEN = Device(id="atv-id", name="Den", device_type=DeviceType.APPLETV, address="127.0.0.3")
BOX = Device(id="uuid:dlna", name="Box", device_type=DeviceType.DLNA, address="127.0.0.4",
             location="http://127.0.0.4/desc.xml")


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg not on PATH")
    path = tmp_path_factory.mktemp("clip") / "Show S01E01.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(path)],
        check=True,
    )
    return path


class FakeSession(CastSession):
    def __init__(self, device: Device, log: list) -> None:
        super().__init__(device)
        self.log = log
        self.played: list[Media] = []
        self.stop_error: Exception | None = None

    def _note(self, action: str) -> None:
        self.log.append((action, self.device.id))

    async def play(self, media: Media) -> None:
        self._note("play")
        self.played.append(media)

    async def pause(self) -> None:
        self._note("pause")

    async def resume(self) -> None:
        self._note("resume")

    async def stop(self) -> None:
        self._note("stop")
        if self.stop_error is not None:
            raise self.stop_error

    async def seek(self, position: float) -> None:
        self._note("seek")

    async def set_volume(self, level: float) -> None:
        self._note("volume")

    async def get_status(self) -> PlaybackStatus:
        return PlaybackStatus()

    async def close(self) -> None:
        self._note("close")


class FakeAdapters:
    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        self.sessions: list[FakeSession] = []
        self.pin_prompts: list = []
        self.open_error: Exception | None = None

    async def open(self, device: Device, request_pin) -> FakeSession:
        self.log.append(("open", device.id))
        self.pin_prompts.append(request_pin)
        if self.open_error is not None:
            raise self.open_error
        session = FakeSession(device, self.log)
        self.sessions.append(session)
        return session


async def no_pin(device_name: str) -> str:
    raise AssertionError("no PIN expected")


@pytest.fixture
def adapters() -> FakeAdapters:
    return FakeAdapters()


@pytest.fixture
def orch(adapters) -> CastOrchestrator:
    return CastOrchestrator(open_session=adapters.open)


async def test_switching_devices_stops_and_closes_the_old_session_first(orch, adapters, clip):
    await orch.cast_file(clip, TV, no_pin)
    await orch.cast_file(clip, DEN, no_pin)
    await orch.cast_file(clip, TV, no_pin)

    opens_and_closes = [e for e in adapters.log if e[0] in ("open", "stop", "close")]
    assert opens_and_closes == [
        ("open", "cc-uuid"), ("stop", "cc-uuid"),
        ("stop", "cc-uuid"), ("close", "cc-uuid"), ("open", "atv-id"), ("stop", "atv-id"),
        ("stop", "atv-id"), ("close", "atv-id"), ("open", "cc-uuid"), ("stop", "cc-uuid"),
    ]
    assert len(adapters.sessions) == 3
    assert adapters.sessions[2] is not adapters.sessions[0]


async def test_every_adapter_gets_the_same_media_facts(orch, adapters, clip):
    await orch.cast_file(clip, TV, no_pin)
    await orch.cast_file(clip, DEN, no_pin)

    for session in adapters.sessions:
        [media] = session.played
        assert media.url.startswith("http://") and "/file/" in media.url
        assert media.content_type == "video/mp4"
        assert media.title == "Show S01E01"
        assert media.duration == pytest.approx(1.0, abs=0.1)


async def test_a_rescan_with_the_same_id_keeps_the_session(orch, adapters, clip):
    await orch.cast_file(clip, TV, no_pin)
    moved = Device(id=TV.id, name=TV.name, device_type=TV.device_type,
                   address="127.0.0.9", port=8009)

    await orch.cast_file(clip, moved, no_pin)

    assert [e for e in adapters.log if e[0] == "open"] == [("open", "cc-uuid")]


async def test_switch_goes_ahead_when_the_old_device_cannot_stop(orch, adapters, clip):
    await orch.cast_file(clip, TV, no_pin)
    adapters.sessions[0].stop_error = OSError("host unreachable")

    await orch.cast_file(clip, DEN, no_pin)

    assert ("close", "cc-uuid") in adapters.log
    assert adapters.sessions[1].played


async def test_the_pin_prompt_reaches_session_open(orch, adapters, clip):
    await orch.cast_file(clip, DEN, no_pin)
    assert adapters.pin_prompts == [no_pin]


async def test_open_errors_reach_the_caller(orch, adapters, clip):
    adapters.open_error = PairingFailed("Pairing with Den failed")
    with pytest.raises(PairingFailed):
        await orch.cast_file(clip, DEN, no_pin)


async def test_stop_closes_the_session(orch, adapters, clip):
    await orch.start()
    await orch.cast_file(clip, TV, no_pin)
    await orch.stop()
    assert adapters.log[-1] == ("close", "cc-uuid")


class FakeStream(Stream):
    def __init__(self, plan, log: list) -> None:
        self.plan = plan
        self.log = log
        self.media = Media(url=f"http://fake/{len(log)}", content_type="video/mp4",
                           title="Show S01E01", duration=1.0)

    async def seek(self, session: CastSession, position: float) -> None:
        self.log.append(("stream_seek", position))
        await session.seek(position)

    async def teardown(self) -> None:
        self.log.append(("teardown", self.plan))


class FakeStreams:
    def __init__(self, log: list) -> None:
        self.log = log
        self.opened: list[FakeStream] = []

    async def open(self, plan, path, probed, server, device_ip) -> FakeStream:
        self.log.append(("open_stream", plan))
        stream = FakeStream(plan, self.log)
        self.opened.append(stream)
        return stream


@pytest.fixture
def streams(adapters) -> FakeStreams:
    return FakeStreams(adapters.log)


@pytest.fixture
def faked(adapters, streams) -> CastOrchestrator:
    return CastOrchestrator(open_session=adapters.open, open_stream=streams.open)


@pytest.fixture(scope="module")
def mkv_clip(clip, tmp_path_factory):
    path = tmp_path_factory.mktemp("mkv") / "Show S01E02.mkv"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(clip),
                    "-c", "copy", str(path)], check=True)
    return path


async def test_the_plan_comes_from_the_device_type(faked, streams, clip, mkv_clip):
    await faked.cast_file(clip, BOX, no_pin)
    await faked.cast_file(mkv_clip, BOX, no_pin)
    assert [s.plan for s in streams.opened] == [
        Direct(), Pipe(transcode_video=False, transcode_audio=False),
    ]


async def test_casting_again_tears_down_the_previous_stream_first(faked, adapters, clip):
    await faked.cast_file(clip, TV, no_pin)
    await faked.cast_file(clip, TV, no_pin)
    stream_events = [e[0] for e in adapters.log if e[0] in ("open_stream", "teardown")]
    assert stream_events == ["open_stream", "teardown", "open_stream"]


async def test_seek_goes_through_the_stream(faked, adapters, clip):
    await faked.cast_file(clip, TV, no_pin)
    await faked.seek(12.0)
    assert adapters.log[-2:] == [("stream_seek", 12.0), ("seek", "cc-uuid")]


async def test_a_seek_after_stop_does_nothing(faked, adapters, clip):
    await faked.cast_file(clip, BOX, no_pin)
    await faked.stop_playback()
    before = list(adapters.log)

    await faked.seek(30.0)

    assert adapters.log == before


async def test_stop_tears_down_even_when_the_device_refuses(faked, adapters, streams, clip):
    await faked.cast_file(clip, BOX, no_pin)
    adapters.sessions[0].stop_error = DeviceRequestFailed("Box didn't stop: 701")

    with pytest.raises(DeviceRequestFailed, match="Box didn't stop: 701"):
        await faked.stop_playback()

    assert adapters.log[-1] == ("teardown", Direct())
    await faked.seek(5.0)
    assert ("stream_seek", 5.0) not in adapters.log


async def test_a_stop_timeout_reaches_the_caller_after_teardown(faked, adapters, clip):
    await faked.cast_file(clip, TV, no_pin)
    adapters.sessions[0].stop_error = TimeoutError("slow")
    with pytest.raises(TimeoutError):
        await faked.stop_playback()
    assert adapters.log[-1][0] == "teardown"


async def test_casting_goes_ahead_when_the_previous_stop_fails(faked, adapters, streams, clip):
    await faked.cast_file(clip, TV, no_pin)
    adapters.sessions[0].stop_error = OSError("gone")
    await faked.cast_file(clip, TV, no_pin)
    assert len(streams.opened) == 2
    assert len(adapters.sessions[0].played) == 2


async def test_shutdown_closes_even_when_the_device_refuses_to_stop(faked, adapters, clip):
    await faked.start()
    await faked.cast_file(clip, TV, no_pin)
    adapters.sessions[0].stop_error = OSError("gone")
    await faked.stop()
    assert adapters.log[-1] == ("close", "cc-uuid")


async def test_a_pipe_seek_restarts_ffmpeg_and_replays(orch, adapters, mkv_clip):
    await orch.start()
    try:
        await orch.cast_file(mkv_clip, BOX, no_pin)
        session = adapters.sessions[0]
        await orch.seek(0.5)
        first, second = session.played
        assert "/stream/" in first.url and "/stream/" in second.url
        assert first.url != second.url
        assert second.content_type == "video/mp4"
    finally:
        await orch.stop()


async def test_an_hls_stream_seeks_natively_and_is_removed_on_stop(orch, adapters, mkv_clip):
    await orch.start()
    try:
        await orch.cast_file(mkv_clip, DEN, no_pin)
        [media] = adapters.sessions[0].played
        assert media.content_type == "application/vnd.apple.mpegurl"
        assert media.url.endswith("/playlist.m3u8")
        assert orch.server._hls

        await orch.seek(0.5)
        assert adapters.log[-1] == ("seek", "atv-id")

        await orch.stop_playback()
        assert not orch.server._hls
    finally:
        await orch.stop()

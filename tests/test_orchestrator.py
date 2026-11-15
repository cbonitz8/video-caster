from __future__ import annotations

import shutil
import subprocess

import pytest

from video_caster.casting.base import CastSession, Media, PairingFailed, PlaybackStatus
from video_caster.casting.orchestrator import CastOrchestrator
from video_caster.discovery.device import Device, DeviceType

TV = Device(id="cc-uuid", name="Living Room", device_type=DeviceType.CHROMECAST,
            address="127.0.0.2", port=8009)
DEN = Device(id="atv-id", name="Den", device_type=DeviceType.APPLETV, address="127.0.0.3")


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

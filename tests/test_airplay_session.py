from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pyatv.const import DeviceState, PairingRequirement, Protocol
from pyatv.exceptions import (
    AuthenticationError,
    BlockedStateError,
    CommandError,
    ConnectionLostError,
    HttpError,
    NotSupportedError,
    OperationTimeoutError,
    PairingError,
    PlaybackError,
)

from video_caster.casting.airplay import AirPlaySession, open_airplay
from video_caster.casting.base import CredentialsRejected, DeviceRequestFailed, Media, PairingFailed
from video_caster.discovery.device import Device, DeviceType

DEN = Device(id="atv-id", name="Den", device_type=DeviceType.APPLETV, address="192.0.2.30")
MOVIE = Media(url="http://host/file/1", content_type="video/mp4", title="Movie", duration=60.0)


class FakeConfig:
    def __init__(self, requirement: PairingRequirement) -> None:
        self.service = SimpleNamespace(pairing=requirement)
        self.credentials: dict = {}

    def get_service(self, protocol):
        assert protocol == Protocol.AirPlay
        return self.service

    def set_credentials(self, protocol, credentials) -> bool:
        self.credentials[protocol] = credentials
        return True


class FakePairing:
    def __init__(self, *, succeeds: bool = True, finish_error: Exception | None = None) -> None:
        self.device_provides_pin = True
        self.succeeds = succeeds
        self.finish_error = finish_error
        self.entered: int | None = None
        self.closed = False
        self.credentials = "fresh-credential"

    async def begin(self) -> None:
        pass

    def pin(self, pin: int) -> None:
        self.entered = pin

    async def finish(self) -> None:
        if self.finish_error is not None:
            raise self.finish_error

    @property
    def has_paired(self) -> bool:
        return self.succeeds

    async def close(self) -> None:
        self.closed = True


class FakeAppleTV:
    def __init__(self, play_error: Exception | None = None) -> None:
        self.played: list[str] = []
        self.closed = False
        self.play_error = play_error
        self.stream = SimpleNamespace(play_url=self._play_url)

    async def _play_url(self, url: str) -> None:
        if self.play_error is not None:
            raise self.play_error
        self.played.append(url)

    def close(self) -> None:
        self.closed = True


class FakePyatv:
    def __init__(self, requirement=PairingRequirement.Mandatory, *, pairing=None,
                 connect_error=None, atv=None) -> None:
        self.config = FakeConfig(requirement)
        self.pairing = pairing if pairing is not None else FakePairing()
        self.connect_error = connect_error
        self.atv = atv if atv is not None else FakeAppleTV()
        self.scans: list[dict] = []
        self.paired = 0

    async def scan(self, loop, *, identifier, hosts, timeout):
        self.scans.append({"identifier": identifier, "hosts": hosts})
        return [self.config]

    async def pair(self, config, protocol, loop):
        assert protocol == Protocol.AirPlay
        self.paired += 1
        return self.pairing

    async def connect(self, config, loop):
        if self.connect_error is not None:
            raise self.connect_error
        return self.atv


class PinPad:
    def __init__(self, pin: str = "1234", error: Exception | None = None) -> None:
        self.pin = pin
        self.error = error
        self.asked: list[str] = []

    async def __call__(self, device_name: str) -> str:
        self.asked.append(device_name)
        if self.error is not None:
            raise self.error
        return self.pin


@pytest.fixture
def creds(tmp_path):
    return tmp_path / "credentials.json"


async def test_unpaired_device_asks_for_one_pin_and_saves_the_credential(creds):
    fake, pin = FakePyatv(), PinPad("4821")

    session = await open_airplay(DEN, pin, credentials_path=creds, pyatv=fake)
    await session.play(MOVIE)

    assert pin.asked == ["Den"]
    assert fake.pairing.entered == 4821
    assert fake.pairing.closed
    assert json.loads(creds.read_text()) == {"atv-id": "fresh-credential"}
    assert fake.config.credentials == {Protocol.AirPlay: "fresh-credential"}
    assert fake.scans == [{"identifier": "atv-id", "hosts": ["192.0.2.30"]}]
    assert fake.atv.played == ["http://host/file/1"]


async def test_stored_credential_skips_pairing(creds):
    creds.write_text(json.dumps({"atv-id": "saved"}))
    fake, pin = FakePyatv(), PinPad()

    await open_airplay(DEN, pin, credentials_path=creds, pyatv=fake)

    assert pin.asked == []
    assert fake.paired == 0
    assert fake.config.credentials == {Protocol.AirPlay: "saved"}


async def test_device_that_needs_no_pairing_never_asks(creds):
    fake, pin = FakePyatv(PairingRequirement.NotNeeded), PinPad()

    await open_airplay(DEN, pin, credentials_path=creds, pyatv=fake)

    assert pin.asked == []
    assert not creds.exists()


async def test_rejected_pin_raises_pairing_failed(creds):
    fake = FakePyatv(pairing=FakePairing(finish_error=PairingError("bad pin")))

    with pytest.raises(PairingFailed):
        await open_airplay(DEN, PinPad(), credentials_path=creds, pyatv=fake)

    assert fake.pairing.closed
    assert not creds.exists()


async def test_pairing_that_does_not_complete_raises_pairing_failed(creds):
    fake = FakePyatv(pairing=FakePairing(succeeds=False))

    with pytest.raises(PairingFailed):
        await open_airplay(DEN, PinPad(), credentials_path=creds, pyatv=fake)


async def test_non_numeric_pin_raises_pairing_failed(creds):
    with pytest.raises(PairingFailed):
        await open_airplay(DEN, PinPad("abcd"), credentials_path=creds, pyatv=FakePyatv())


async def test_pin_timeout_propagates(creds):
    timeout = TimeoutError("No PIN entered for Den within 120s")
    fake = FakePyatv()

    with pytest.raises(TimeoutError) as raised:
        await open_airplay(DEN, PinPad(error=timeout), credentials_path=creds, pyatv=fake)

    assert raised.value is timeout
    assert fake.pairing.closed


async def test_stale_credential_on_connect_is_forgotten(creds):
    creds.write_text(json.dumps({"atv-id": "stale", "other-id": "keep"}))
    fake = FakePyatv(connect_error=AuthenticationError("not authenticated"))

    with pytest.raises(CredentialsRejected):
        await open_airplay(DEN, PinPad(), credentials_path=creds, pyatv=fake)

    assert json.loads(creds.read_text()) == {"other-id": "keep"}


async def test_stale_credential_on_play_is_forgotten(creds):
    creds.write_text(json.dumps({"atv-id": "stale"}))
    fake = FakePyatv(atv=FakeAppleTV(play_error=AuthenticationError("not authenticated")))
    session = await open_airplay(DEN, PinPad(), credentials_path=creds, pyatv=fake)

    with pytest.raises(CredentialsRejected):
        await session.play(MOVIE)

    assert json.loads(creds.read_text()) == {}


async def test_device_missing_from_unicast_scan_raises(creds):
    fake = FakePyatv()

    async def nothing(loop, *, identifier, hosts, timeout):
        return []

    fake.scan = nothing
    with pytest.raises(RuntimeError, match="Den"):
        await open_airplay(DEN, PinPad(), credentials_path=creds, pyatv=fake)


class RefusingAppleTV:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.remote_control = SimpleNamespace(
            pause=self._refuse, play=self._refuse, stop=self._refuse, set_position=self._refuse,
        )
        self.audio = SimpleNamespace(set_volume=self._refuse)
        self.metadata = SimpleNamespace(playing=self._refuse)

    async def _refuse(self, *args) -> None:
        raise self.error


CONTROLS = [
    ("pause", (), "pause"),
    ("resume", (), "resume"),
    ("stop", (), "stop"),
    ("seek", (12.0,), "seek"),
    ("set_volume", (0.5,), "change volume"),
    ("get_status", (), "report status"),
]


@pytest.mark.parametrize("method, args, action", CONTROLS)
@pytest.mark.parametrize("error", [
    CommandError("refused"),
    ConnectionLostError("gone"),
    PlaybackError("no"),
    BlockedStateError("blocked"),
    HttpError("bad", 500),
])
async def test_a_refused_request_is_a_device_request_failure(creds, method, args, action, error):
    session = AirPlaySession(DEN, RefusingAppleTV(error), creds)
    with pytest.raises(DeviceRequestFailed, match=f"Den didn't {action}"):
        await getattr(session, method)(*args)


@pytest.mark.parametrize("method, args, action", CONTROLS)
async def test_a_request_timeout_is_a_plain_timeout(creds, method, args, action):
    session = AirPlaySession(DEN, RefusingAppleTV(OperationTimeoutError("slow")), creds)
    with pytest.raises(TimeoutError, match=f"Den didn't answer {action}"):
        await getattr(session, method)(*args)


async def test_an_unexpected_error_is_not_dressed_up_as_a_device_failure(creds):
    session = AirPlaySession(DEN, RefusingAppleTV(KeyError("bug")), creds)
    with pytest.raises(KeyError):
        await session.pause()


class PlayingAppleTV:
    def __init__(self) -> None:
        playing = SimpleNamespace(device_state=DeviceState.Playing, position=65,
                                  total_time=1200, title="Pilot")
        self.metadata = SimpleNamespace(playing=lambda: _reply(playing))
        self.audio = UnsupportedAudio()


class UnsupportedAudio:
    @property
    def volume(self) -> float:
        raise NotSupportedError()


async def _reply(value):
    return value


async def test_an_apple_tv_without_volume_still_reports_status(creds):
    status = await AirPlaySession(DEN, PlayingAppleTV(), creds).get_status()
    assert (status.state, status.current_time, status.duration, status.volume) == (
        "playing", 65, 1200, 1.0)

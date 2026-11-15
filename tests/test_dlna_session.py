from __future__ import annotations

import pytest
from async_upnp_client.exceptions import (
    UpnpActionError,
    UpnpCommunicationError,
    UpnpConnectionTimeoutError,
)

from video_caster.casting.base import DeviceRequestFailed
from video_caster.casting.dlna import DLNASession
from video_caster.discovery.device import Device, DeviceType

BOX = Device(id="uuid:dlna", name="Box", device_type=DeviceType.DLNA, address="127.0.0.4",
             location="http://127.0.0.4/desc.xml")


class FakeAction:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.calls = 0

    async def async_call(self, **kwargs) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {}


class FakeService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.actions: dict[str, FakeAction] = {}

    def action(self, name: str) -> FakeAction:
        return self.actions.setdefault(name, FakeAction(self.error))


async def test_stop_sends_stop():
    transport = FakeService()
    await DLNASession(BOX, transport, None).stop()
    assert transport.actions["Stop"].calls == 1


async def test_stopping_an_already_stopped_renderer_is_fine():
    transport = FakeService(UpnpActionError(error_code=701, error_desc="Transition not available"))
    await DLNASession(BOX, transport, None).stop()


CONTROLS = [
    ("pause", (), "pause"),
    ("resume", (), "resume"),
    ("stop", (), "stop"),
    ("seek", (12.0,), "seek"),
    ("set_volume", (0.5,), "change volume"),
]


@pytest.mark.parametrize("method, args, action", CONTROLS)
@pytest.mark.parametrize("error", [
    UpnpActionError(error_code=501, error_desc="Action Failed"),
    UpnpCommunicationError("unreachable"),
])
async def test_a_refused_request_is_a_device_request_failure(method, args, action, error):
    service = FakeService(error)
    session = DLNASession(BOX, service, service)
    with pytest.raises(DeviceRequestFailed, match=f"Box didn't {action}"):
        await getattr(session, method)(*args)


@pytest.mark.parametrize("method, args, action", CONTROLS)
async def test_a_request_timeout_is_a_plain_timeout(method, args, action):
    service = FakeService(UpnpConnectionTimeoutError("slow"))
    session = DLNASession(BOX, service, service)
    with pytest.raises(TimeoutError, match=f"Box didn't answer {action}"):
        await getattr(session, method)(*args)

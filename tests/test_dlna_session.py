from __future__ import annotations

import pytest
from async_upnp_client.exceptions import UpnpActionError, UpnpCommunicationError

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


class FakeTransport:
    def __init__(self, error: Exception | None = None) -> None:
        self.stop = FakeAction(error)

    def action(self, name: str) -> FakeAction:
        assert name == "Stop"
        return self.stop


async def test_stop_sends_stop():
    transport = FakeTransport()
    await DLNASession(BOX, transport, None).stop()
    assert transport.stop.calls == 1


async def test_stopping_an_already_stopped_renderer_is_fine():
    transport = FakeTransport(UpnpActionError(error_code=701, error_desc="Transition not available"))
    await DLNASession(BOX, transport, None).stop()


@pytest.mark.parametrize("error", [
    UpnpActionError(error_code=501, error_desc="Action Failed"),
    UpnpCommunicationError("unreachable"),
])
async def test_other_stop_errors_reach_the_caller(error):
    with pytest.raises(type(error)):
        await DLNASession(BOX, FakeTransport(error), None).stop()

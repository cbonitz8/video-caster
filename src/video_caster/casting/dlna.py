"""DLNA/UPnP MediaRenderer handler using async-upnp-client."""

from __future__ import annotations

import logging
from xml.etree.ElementTree import Element, SubElement, tostring

from async_upnp_client.aiohttp import AiohttpRequester
from async_upnp_client.client import UpnpService
from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.exceptions import UpnpActionError, UpnpError

from video_caster.casting.base import CastSession, Media, PlaybackStatus, device_request
from video_caster.discovery.device import Device

log = logging.getLogger(__name__)

# DLNA transport state → our state
_STATE_MAP = {
    "PLAYING": "playing",
    "PAUSED_PLAYBACK": "paused",
    "STOPPED": "idle",
    "NO_MEDIA_PRESENT": "idle",
    "TRANSITIONING": "buffering",
}


def _didl_metadata(title: str, content_type: str = "video/mp4") -> str:
    """Build minimal DIDL-Lite metadata XML for SetAVTransportURI."""
    root = Element("DIDL-Lite")
    root.set("xmlns", "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/")
    root.set("xmlns:dc", "http://purl.org/dc/elements/1.1/")
    root.set("xmlns:upnp", "urn:schemas-upnp-org:metadata-1-0/upnp/")
    item = SubElement(root, "item", id="0", parentID="-1", restricted="1")
    dc_title = SubElement(item, "dc:title")
    dc_title.text = title or "Video"
    upnp_class = SubElement(item, "upnp:class")
    upnp_class.text = "object.item.videoItem"
    res = SubElement(item, "res", protocolInfo=f"http-get:*:{content_type}:*")
    res.text = ""  # URI gets set separately by SetAVTransportURI
    return tostring(root, encoding="unicode", xml_declaration=False)


AV_TRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
RENDERING_CONTROL = "urn:schemas-upnp-org:service:RenderingControl:1"
# AVTransport answers Stop with this when the renderer is already stopped.
TRANSITION_NOT_AVAILABLE = 701


async def open_dlna(device: Device) -> DLNASession:
    log.info("Connecting to DLNA device: %s", device.name)
    if not device.location:
        raise RuntimeError(f"No description URL for DLNA device {device.name}")
    upnp_device = await UpnpFactory(AiohttpRequester()).async_create_device(device.location)
    av_transport = upnp_device.service(AV_TRANSPORT)
    if not av_transport:
        raise RuntimeError(f"Device {device.name} has no AVTransport service")
    log.info("Connected to DLNA device: %s (%s)", device.name, device.model)
    return DLNASession(device, av_transport, upnp_device.service(RENDERING_CONTROL))


class DLNASession(CastSession):
    def __init__(
        self,
        device: Device,
        av_transport: UpnpService,
        rendering_control: UpnpService | None,
    ) -> None:
        super().__init__(device)
        self._av_transport = av_transport
        self._rendering_control = rendering_control
        self._title = ""

    async def close(self) -> None:
        pass

    async def play(self, media: Media) -> None:
        self._title = media.title
        set_uri = self._av_transport.action("SetAVTransportURI")
        await set_uri.async_call(
            InstanceID=0,
            CurrentURI=media.url,
            CurrentURIMetaData=_didl_metadata(media.title, media.content_type),
        )
        play = self._av_transport.action("Play")
        await play.async_call(InstanceID=0, Speed="1")
        log.info("DLNA playback started: %s", media.url)

    def _request(self, action: str):
        return device_request(self.device, action, timeouts=(TimeoutError,), failures=(UpnpError,))

    async def pause(self) -> None:
        with self._request("pause"):
            await self._av_transport.action("Pause").async_call(InstanceID=0)

    async def resume(self) -> None:
        with self._request("resume"):
            await self._av_transport.action("Play").async_call(InstanceID=0, Speed="1")

    async def stop(self) -> None:
        with self._request("stop"):
            try:
                await self._av_transport.action("Stop").async_call(InstanceID=0)
            except UpnpActionError as e:
                if e.error_code != TRANSITION_NOT_AVAILABLE:
                    raise

    async def seek(self, position: float) -> None:
        h = int(position) // 3600
        m = (int(position) % 3600) // 60
        s = int(position) % 60
        target = f"{h}:{m:02d}:{s:02d}"
        with self._request("seek"):
            await self._av_transport.action("Seek").async_call(InstanceID=0, Unit="REL_TIME", Target=target)

    async def set_volume(self, level: float) -> None:
        if not self._rendering_control:
            return
        # CastSession uses 0.0-1.0, DLNA uses 0-100
        volume = int(level * 100)
        with self._request("change volume"):
            await self._rendering_control.action("SetVolume").async_call(
                InstanceID=0, Channel="Master", DesiredVolume=volume
            )

    async def get_status(self) -> PlaybackStatus:
        with self._request("report status"):
            pos_info = await self._av_transport.action("GetPositionInfo").async_call(InstanceID=0)
            transport_info = await self._av_transport.action("GetTransportInfo").async_call(
                InstanceID=0
            )
            volume = await self._volume()
        transport_state = transport_info.get("CurrentTransportState", "STOPPED")
        return PlaybackStatus(
            state=_STATE_MAP.get(transport_state, "idle"),
            current_time=_parse_time(pos_info.get("RelTime", "0:00:00")),
            duration=_parse_time(pos_info.get("TrackDuration", "0:00:00")),
            volume=volume,
            title=self._title,
        )

    async def _volume(self) -> float:
        if self._rendering_control is None or not self._rendering_control.has_action("GetVolume"):
            return 1.0
        try:
            vol_info = await self._rendering_control.action("GetVolume").async_call(
                InstanceID=0, Channel="Master"
            )
        except UpnpActionError:
            return 1.0
        return int(vol_info.get("CurrentVolume", 100)) / 100.0


def _parse_time(time_str: str) -> float:
    """Parse H:MM:SS or H:MM:SS.f into seconds."""
    try:
        parts = time_str.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError):
        pass
    return 0.0

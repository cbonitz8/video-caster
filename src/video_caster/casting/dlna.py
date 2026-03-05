"""DLNA/UPnP MediaRenderer handler using async-upnp-client."""

from __future__ import annotations

import logging
from xml.etree.ElementTree import Element, SubElement, tostring

from async_upnp_client.aiohttp import AiohttpRequester
from async_upnp_client.client import UpnpDevice, UpnpService
from async_upnp_client.client_factory import UpnpFactory

from video_caster.casting.base import CastHandler, PlaybackStatus
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


class DLNAHandler(CastHandler):
    def __init__(self, device: Device) -> None:
        super().__init__(device)
        self._upnp_device: UpnpDevice | None = None
        self._av_transport: UpnpService | None = None
        self._rendering_control: UpnpService | None = None
        self._requester: AiohttpRequester | None = None
        self._title: str = ""

    async def connect(self) -> None:
        log.info("Connecting to DLNA device: %s", self.device.name)
        location = self.device.protocol_config.get("location")
        if not location:
            raise RuntimeError(f"No description URL for DLNA device {self.device.name}")

        self._requester = AiohttpRequester()
        factory = UpnpFactory(self._requester)
        self._upnp_device = await factory.async_create_device(location)

        # Update device name from description if we only had a UUID
        if self._upnp_device.friendly_name:
            self.device.name = self._upnp_device.friendly_name
            if self._upnp_device.model_name:
                self.device.model = self._upnp_device.model_name

        avt_type = "urn:schemas-upnp-org:service:AVTransport:1"
        rc_type = "urn:schemas-upnp-org:service:RenderingControl:1"

        self._av_transport = self._upnp_device.service(avt_type)
        if not self._av_transport:
            raise RuntimeError(f"Device {self.device.name} has no AVTransport service")

        self._rendering_control = self._upnp_device.service(rc_type)

        log.info("Connected to DLNA device: %s (%s)",
                 self.device.name, self.device.model)

    async def disconnect(self) -> None:
        self._requester = None
        self._upnp_device = None
        self._av_transport = None
        self._rendering_control = None

    async def play_media(self, url: str, content_type: str = "video/mp4") -> None:
        if not self._av_transport:
            raise RuntimeError("Not connected")

        self._title = url.rsplit("/", 1)[-1] if "/" in url else "Video"
        metadata = _didl_metadata(self._title, content_type)

        set_uri = self._av_transport.action("SetAVTransportURI")
        await set_uri.async_call(
            InstanceID=0,
            CurrentURI=url,
            CurrentURIMetaData=metadata,
        )

        play = self._av_transport.action("Play")
        await play.async_call(InstanceID=0, Speed="1")
        log.info("DLNA playback started: %s", url)

    async def pause(self) -> None:
        if self._av_transport:
            action = self._av_transport.action("Pause")
            await action.async_call(InstanceID=0)

    async def resume(self) -> None:
        if self._av_transport:
            action = self._av_transport.action("Play")
            await action.async_call(InstanceID=0, Speed="1")

    async def stop(self) -> None:
        if self._av_transport:
            try:
                action = self._av_transport.action("Stop")
                await action.async_call(InstanceID=0)
            except Exception:
                pass

    async def seek(self, position: float) -> None:
        if not self._av_transport:
            return
        h = int(position) // 3600
        m = (int(position) % 3600) // 60
        s = int(position) % 60
        target = f"{h}:{m:02d}:{s:02d}"
        action = self._av_transport.action("Seek")
        await action.async_call(InstanceID=0, Unit="REL_TIME", Target=target)

    async def set_volume(self, level: float) -> None:
        if not self._rendering_control:
            return
        # CastHandler uses 0.0-1.0, DLNA uses 0-100
        volume = int(level * 100)
        action = self._rendering_control.action("SetVolume")
        await action.async_call(InstanceID=0, Channel="Master", DesiredVolume=volume)

    async def get_status(self) -> PlaybackStatus:
        if not self._av_transport:
            return PlaybackStatus()

        try:
            pos_action = self._av_transport.action("GetPositionInfo")
            pos_info = await pos_action.async_call(InstanceID=0)

            current_time = _parse_time(pos_info.get("RelTime", "0:00:00"))
            duration = _parse_time(pos_info.get("TrackDuration", "0:00:00"))

            transport_action = self._av_transport.action("GetTransportInfo")
            transport_info = await transport_action.async_call(InstanceID=0)
            transport_state = transport_info.get("CurrentTransportState", "STOPPED")
            state = _STATE_MAP.get(transport_state, "idle")

            volume = 1.0
            if self._rendering_control:
                try:
                    vol_action = self._rendering_control.action("GetVolume")
                    vol_info = await vol_action.async_call(
                        InstanceID=0, Channel="Master"
                    )
                    volume = int(vol_info.get("CurrentVolume", 100)) / 100.0
                except Exception:
                    pass

            return PlaybackStatus(
                state=state,
                current_time=current_time,
                duration=duration,
                volume=volume,
                title=self._title,
            )
        except Exception as e:
            log.debug("DLNA get_status failed: %s", e)
            return PlaybackStatus()


def _parse_time(time_str: str) -> float:
    """Parse H:MM:SS or H:MM:SS.f into seconds."""
    try:
        parts = time_str.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError):
        pass
    return 0.0

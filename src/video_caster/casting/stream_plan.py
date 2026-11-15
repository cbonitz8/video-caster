"""How a file reaches a device: served as is, piped through ffmpeg, or as HLS."""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Union

from video_caster.casting.base import CastSession, Media
from video_caster.discovery.device import DeviceType
from video_caster.server.media_server import MediaServer
from video_caster.transcoding.hls import HlsSession
from video_caster.transcoding.probe import ProbeResult
from video_caster.transcoding.transcoder import Transcoder

log = logging.getLogger(__name__)

MP4 = "video/mp4"
M3U8 = "application/vnd.apple.mpegurl"


@dataclass(frozen=True)
class Capabilities:
    video_codecs: frozenset[str]
    audio_codecs: frozenset[str]
    containers: frozenset[str]
    speaks_hls: bool
    stereo_only: bool


_CAPABILITIES = {
    DeviceType.CHROMECAST: Capabilities(
        video_codecs=frozenset({"h264", "vp8", "vp9", "av1"}),
        audio_codecs=frozenset({"aac", "mp3", "flac", "opus", "vorbis", "ac3", "eac3"}),
        containers=frozenset({"mp4", "webm", "mkv"}),
        speaks_hls=True,
        stereo_only=True,
    ),
    DeviceType.APPLETV: Capabilities(
        # HEVC over AirPlay is unreliable, so it is always transcoded.
        video_codecs=frozenset({"h264"}),
        audio_codecs=frozenset({"aac", "mp3", "flac", "alac", "ac3"}),
        containers=frozenset({"mp4", "mov"}),
        speaks_hls=True,
        stereo_only=False,
    ),
    DeviceType.DLNA: Capabilities(
        video_codecs=frozenset({"h264"}),
        audio_codecs=frozenset({"aac", "mp3", "ac3"}),
        containers=frozenset({"mp4"}),
        # Many DLNA renderers don't speak HLS.
        speaks_hls=False,
        stereo_only=True,
    ),
}


def capabilities_for(device_type: DeviceType) -> Capabilities:
    try:
        return _CAPABILITIES[device_type]
    except KeyError:
        raise ValueError(f"No capabilities known for device type {device_type!r}") from None


@dataclass(frozen=True)
class Direct:
    pass


@dataclass(frozen=True)
class Pipe:
    transcode_video: bool
    transcode_audio: bool


@dataclass(frozen=True)
class Hls:
    transcode_video: bool
    transcode_audio: bool


Plan = Union[Direct, Pipe, Hls]


def choose_plan(probed: ProbeResult, caps: Capabilities) -> Plan:
    video_ok = probed.video_codec.lower() in caps.video_codecs
    container_ok = probed.container.lower() in caps.containers
    # Default Chromecast/DLNA receivers flake on multichannel (>2ch) AAC with
    # LOAD_FAILED, so those get a stereo downmix.
    too_many_channels = caps.stereo_only and probed.audio_channels > 2
    audio_ok = probed.audio_codec.lower() in caps.audio_codecs and not too_many_channels

    if video_ok and audio_ok and container_ok:
        return Direct()
    if caps.speaks_hls:
        return Hls(transcode_video=not video_ok, transcode_audio=not audio_ok)
    return Pipe(transcode_video=not video_ok, transcode_audio=not audio_ok)


class Stream(ABC):
    """A plan running for one file: registered with the media server until torn down."""

    media: Media

    @abstractmethod
    async def seek(self, session: CastSession, position: float) -> None: ...

    @abstractmethod
    async def teardown(self) -> None: ...


OpenStream = Callable[[Plan, Path, ProbeResult, MediaServer, str], Awaitable[Stream]]


async def open_stream(
    plan: Plan, path: Path, probed: ProbeResult, server: MediaServer, device_ip: str
) -> Stream:
    if isinstance(plan, Direct):
        return DirectStream.open(path, probed, server, device_ip)
    if isinstance(plan, Pipe):
        return await PipeStream.open(plan, path, probed, server, device_ip)
    return await HlsStream.open(plan, path, probed, server, device_ip)


class DirectStream(Stream):
    def __init__(self, media: Media) -> None:
        self.media = media

    @classmethod
    def open(cls, path: Path, probed: ProbeResult, server: MediaServer, device_ip: str) -> DirectStream:
        url = server.register_file(str(uuid.uuid4()), path, device_ip)
        log.info("Serving file directly at %s", url)
        return cls(Media(url=url, content_type=MP4, title=path.stem, duration=probed.duration))

    async def seek(self, session: CastSession, position: float) -> None:
        await session.seek(position)

    async def teardown(self) -> None:
        pass


class PipeStream(Stream):
    def __init__(self, plan: Pipe, path: Path, probed: ProbeResult,
                 server: MediaServer, device_ip: str) -> None:
        self._plan = plan
        self._path = path
        self._duration = probed.duration
        self._server = server
        self._device_ip = device_ip
        self._transcoder = Transcoder()
        self._stream_id: str | None = None

    @classmethod
    async def open(cls, plan: Pipe, path: Path, probed: ProbeResult,
                   server: MediaServer, device_ip: str) -> PipeStream:
        stream = cls(plan, path, probed, server, device_ip)
        await stream._start(0.0)
        return stream

    async def _start(self, seek_to: float) -> None:
        output = await self._transcoder.start(
            self._path,
            transcode_video=self._plan.transcode_video,
            transcode_audio=self._plan.transcode_audio,
            seek_to=seek_to,
        )
        self._stream_id = str(uuid.uuid4())
        url = self._server.register_stream(self._stream_id, output, self._device_ip)
        log.info("Serving transcoded stream at %s", url)
        self.media = Media(url=url, content_type=MP4, title=self._path.stem, duration=self._duration)

    async def _stop(self) -> None:
        await self._transcoder.stop()
        if self._stream_id is not None:
            self._server.unregister_stream(self._stream_id)
            self._stream_id = None

    async def seek(self, session: CastSession, position: float) -> None:
        log.info("Seek %.1fs on transcoded pipe — restarting ffmpeg", position)
        await self._stop()
        await self._start(position)
        await session.play(self.media)

    async def teardown(self) -> None:
        await self._stop()


class HlsStream(Stream):
    def __init__(self, hls: HlsSession, server: MediaServer, stream_id: str, media: Media) -> None:
        self._hls = hls
        self._server = server
        self._stream_id = stream_id
        self.media = media

    @classmethod
    async def open(cls, plan: Hls, path: Path, probed: ProbeResult,
                   server: MediaServer, device_ip: str) -> HlsStream:
        hls = await HlsSession.open(path, probed, copy_video=not plan.transcode_video,
                                    transcode_audio=plan.transcode_audio)
        stream_id = str(uuid.uuid4())
        url = server.register_hls(stream_id, hls, device_ip)
        log.info("Serving HLS at %s (copy_video=%s)", url, hls.copy_video)
        return cls(hls, server, stream_id,
                   Media(url=url, content_type=M3U8, title=path.stem, duration=probed.duration))

    async def seek(self, session: CastSession, position: float) -> None:
        await session.seek(position)

    async def teardown(self) -> None:
        self._server.unregister_hls(self._stream_id)
        await self._hls.close()

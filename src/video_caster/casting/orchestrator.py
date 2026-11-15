"""Coordinates file probing, transcoding, serving, and casting."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from video_caster.casting.base import (
    CastSession,
    Media,
    OpenSession,
    PlaybackStatus,
    RequestPin,
)
from video_caster.discovery.device import Device, DeviceType
from video_caster.server.media_server import MediaServer
from video_caster.transcoding.formats import needs_transcode
from video_caster.transcoding.hls import HLS_SEGMENT_DURATION, HLSTranscoder
from video_caster.transcoding.probe import (
    ProbeResult,
    group_keyframes_into_segments,
    probe,
    probe_keyframes,
)
from video_caster.transcoding.transcoder import Transcoder

log = logging.getLogger(__name__)

# How far ahead of the current encode position the receiver may request before
# we restart ffmpeg at that offset (otherwise we'd wait forever for the encode
# to catch up on a far-forward seek).
HLS_FAR_SEEK_THRESHOLD = 5  # segments


class CastOrchestrator:
    def __init__(self, open_session: OpenSession) -> None:
        self.server = MediaServer()
        self._open_session = open_session
        self._transcoder = Transcoder()  # used for DLNA fallback path
        self._hls = HLSTranscoder()
        self._session: CastSession | None = None
        self._current_stream_id: str | None = None
        self._current_cast: dict | None = None

    async def start(self) -> None:
        await self.server.start()

    async def stop(self) -> None:
        await self.stop_playback()
        if self._session is not None:
            session, self._session = self._session, None
            await session.close()
        await self.server.stop()

    async def _switch_to(self, device: Device, request_pin: RequestPin) -> None:
        old, self._session = self._session, None
        if old is not None:
            try:
                await old.stop()
            except Exception:
                log.warning("Couldn't stop %s before switching", old.device.name, exc_info=True)
            try:
                await old.close()
            except Exception:
                log.warning("Couldn't close %s before switching", old.device.name, exc_info=True)
        self._session = await self._open_session(device, request_pin)

    async def cast_file(self, file_path: Path, device: Device, request_pin: RequestPin) -> None:
        """Probe, transcode if needed, serve, and cast a file."""
        log.info("Casting %s to %s", file_path.name, device.name)

        if self._session is None or self._session.device.id != device.id:
            await self._switch_to(device, request_pin)

        await self.stop_playback()

        probe_result = await probe(file_path)
        if not probe_result.video_codec:
            raise RuntimeError(f"Could not probe {file_path.name}")

        target = device.device_type.value
        need_video, need_audio, need_remux = needs_transcode(
            probe_result.video_codec,
            probe_result.audio_codec,
            probe_result.container,
            target,
            probe_result.audio_channels,
        )

        title = file_path.stem
        duration = probe_result.duration
        is_transcoded = need_video or need_audio or need_remux

        # Chromecast/AirPlay get HLS for transcoded streams (correct duration,
        # native seek). DLNA stays on fragmented-mp4 pipe — many DLNA renderers
        # don't speak HLS.
        use_hls = is_transcoded and device.device_type in (
            DeviceType.CHROMECAST,
            DeviceType.APPLETV,
        )

        content_type = "video/mp4"
        copy_video = False
        segment_starts: list[float] = []
        if use_hls:
            url, copy_video, segment_starts = await self._serve_hls(
                file_path, need_video, need_audio, duration, device.address
            )
            content_type = "application/vnd.apple.mpegurl"
            log.info("Serving HLS at %s (copy_video=%s)", url, copy_video)
        elif is_transcoded:
            url = await self._serve_transcoded(
                file_path, need_video, need_audio, device.address
            )
            log.info("Serving transcoded stream at %s", url)
        else:
            file_id = str(uuid.uuid4())
            url = self.server.register_file(file_id, file_path, device.address)
            log.info("Serving file directly at %s", url)

        self._current_cast = {
            "path": file_path,
            "device": device,
            "need_video": need_video,
            "need_audio": need_audio,
            "need_remux": need_remux,
            "duration": duration,
            "title": title,
            "transcoded": is_transcoded,
            "use_hls": use_hls,
            "copy_video": copy_video,
            "segment_starts": segment_starts,
        }
        await self._session.play(
            Media(url=url, content_type=content_type, title=title, duration=duration)
        )

    async def _serve_hls(
        self,
        path: Path,
        transcode_video: bool,
        transcode_audio: bool,
        duration: float,
        device_ip: str,
    ) -> tuple[str, bool, list[float]]:
        """Returns (playlist_url, copy_video, segment_starts).

        segment_starts is empty when video is re-encoded.
        """
        copy_video = not transcode_video
        # When copying, derive segment boundaries from the source's actual
        # keyframes — that's what `-c:v copy -hls_time` will land on, and the
        # synthesized playlist must match exactly to keep playback in sync.
        segment_starts: list[float] = []
        segment_durations: list[float] | None = None
        if copy_video:
            keyframes = await probe_keyframes(path)
            grouped = group_keyframes_into_segments(
                keyframes, duration, HLS_SEGMENT_DURATION
            )
            if grouped:
                segment_starts = [s for s, _ in grouped]
                segment_durations = [d for _, d in grouped]
            else:
                log.warning(
                    "Keyframe probe returned nothing for %s; falling back to re-encode",
                    path.name,
                )
                copy_video = False

        await self._hls.start(
            path,
            copy_video=copy_video,
            transcode_audio=transcode_audio,
            seek_to=0.0,
            start_segment=0,
        )
        stream_id = str(uuid.uuid4())
        self._current_stream_id = stream_id
        assert self._hls.output_dir is not None
        url = self.server.register_hls(
            stream_id,
            self._hls.output_dir,
            duration,
            ensure_segment=self._ensure_hls_segment,
            segment_duration=self._hls.real_segment_duration(),
            segments=segment_durations,
            device_ip=device_ip,
        )
        return url, copy_video, segment_starts

    async def _ensure_hls_segment(self, stream_id: str, segment_index: int) -> None:
        """Restart ffmpeg at segment_index when receiver seeks far ahead."""
        if stream_id != self._current_stream_id or self._current_cast is None:
            return
        current = self._hls.current_segment_index()
        # ffmpeg only encodes forward from start_segment: a missing segment
        # behind it never arrives, so only wait when it's just ahead.
        if self._hls.start_segment <= segment_index <= current + HLS_FAR_SEEK_THRESHOLD:
            return

        cast = self._current_cast
        # Pick a real keyframe-aligned offset when copying video. Otherwise the
        # nominal segment-index * segment-duration is fine (re-encode forces
        # keyframes at those points).
        starts = cast.get("segment_starts") or []
        if cast.get("copy_video") and segment_index < len(starts):
            seek_to = starts[segment_index]
        else:
            seek_to = segment_index * HLS_SEGMENT_DURATION
        log.info(
            "HLS far seek to seg %d (%.1fs); restarting ffmpeg",
            segment_index, seek_to,
        )
        await self._hls.start(
            cast["path"],
            copy_video=cast.get("copy_video", not cast["need_video"]),
            transcode_audio=cast["need_audio"],
            seek_to=seek_to,
            start_segment=segment_index,
        )

    async def _serve_transcoded(
        self,
        path: Path,
        transcode_video: bool,
        transcode_audio: bool,
        device_ip: str = "",
        seek_to: float = 0.0,
    ) -> str:
        stream = await self._transcoder.start(
            path,
            transcode_video=transcode_video,
            transcode_audio=transcode_audio,
            seek_to=seek_to,
        )
        stream_id = str(uuid.uuid4())
        self._current_stream_id = stream_id
        return self.server.register_stream(stream_id, stream, device_ip)

    async def stop_playback(self) -> None:
        if self._session:
            try:
                await self._session.stop()
            except Exception:
                pass

        await self._transcoder.stop()
        await self._hls.cleanup()

        if self._current_stream_id:
            self.server.unregister_stream(self._current_stream_id)
            self.server.unregister_hls(self._current_stream_id)
            self._current_stream_id = None

    async def toggle_pause(self) -> None:
        if self._session:
            status = await self._session.get_status()
            if status.state == "playing":
                await self._session.pause()
            else:
                await self._session.resume()

    async def seek(self, position: float) -> None:
        if not self._session:
            return

        # Native seek works for: direct files (server Range), and HLS (receiver
        # fetches the right segments; ensure_segment callback restarts ffmpeg
        # if the seek is far ahead of the encoded buffer).
        if (
            not self._current_cast
            or not self._current_cast.get("transcoded")
            or self._current_cast.get("use_hls")
        ):
            await self._session.seek(position)
            return

        # DLNA transcoded path (fragmented mp4 pipe): restart ffmpeg at offset.
        cast = self._current_cast
        log.info("Seek %.1fs on transcoded pipe — restarting ffmpeg", position)
        await self._transcoder.stop()
        if self._current_stream_id:
            self.server.unregister_stream(self._current_stream_id)
            self._current_stream_id = None

        url = await self._serve_transcoded(
            cast["path"],
            cast["need_video"],
            cast["need_audio"],
            cast["device"].address,
            seek_to=position,
        )
        await self._session.play(
            Media(url=url, content_type="video/mp4", title=cast["title"], duration=cast["duration"])
        )

    async def set_volume(self, level: float) -> None:
        if self._session:
            await self._session.set_volume(max(0.0, min(1.0, level)))

    async def get_status(self) -> PlaybackStatus:
        if self._session:
            return await self._session.get_status()
        return PlaybackStatus()

"""FFmpeg subprocess manager for transcoding/remuxing video files."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

log = logging.getLogger(__name__)


class Transcoder:
    """Manages an FFmpeg subprocess that outputs fragmented MP4 to stdout."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(
        self,
        input_path: Path,
        *,
        transcode_video: bool = False,
        transcode_audio: bool = False,
        seek_to: float = 0.0,
    ) -> AsyncIterator[bytes]:
        """Start FFmpeg and yield output chunks.

        Args:
            input_path: Path to input video file.
            transcode_video: If True, re-encode video to H.264. Otherwise copy.
            transcode_audio: If True, re-encode audio to AAC. Otherwise copy.
            seek_to: Seek to this position (seconds) before transcoding.
        """
        await self.stop()

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]

        if seek_to > 0:
            cmd += ["-ss", str(seek_to)]

        cmd += ["-i", str(input_path)]

        # Video codec
        if transcode_video:
            cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "22"]
        else:
            cmd += ["-c:v", "copy"]

        # Audio codec
        if transcode_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c:a", "copy"]

        # Output fragmented MP4 to stdout
        cmd += [
            "-movflags", "frag_keyframe+empty_moov+faststart",
            "-f", "mp4",
            "pipe:1",
        ]

        log.info("Starting FFmpeg: %s", " ".join(cmd))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        return self._read_output()

    async def _read_output(self) -> AsyncIterator[bytes]:
        """Read chunks from FFmpeg stdout."""
        assert self._process is not None
        assert self._process.stdout is not None

        try:
            while True:
                chunk = await self._process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        except asyncio.CancelledError:
            log.debug("Transcoder read cancelled")
            raise
        finally:
            if self._process.returncode is None:
                self._process.kill()
            await self._process.wait()

            # Log any FFmpeg errors
            if self._process.stderr:
                stderr = await self._process.stderr.read()
                if stderr and self._process.returncode != 0:
                    log.error("FFmpeg stderr: %s", stderr.decode(errors="replace"))

            self._process = None

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            log.info("Stopping FFmpeg process")
            self._process.kill()
            await self._process.wait()
            self._process = None

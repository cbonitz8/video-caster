"""HLS transcoder — writes TS segments + playlist to a temp directory."""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

HLS_SEGMENT_DURATION = 6.0
SEGMENT_NAME_RE = re.compile(r"^seg-(\d{5})\.ts$")


class HLSTranscoder:
    """FFmpeg-managed HLS output. One temp dir per cast session."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._tmpdir: Path | None = None
        self._start_segment: int = 0
        self._stderr_task: asyncio.Task | None = None

    @property
    def output_dir(self) -> Path | None:
        return self._tmpdir

    @property
    def start_segment(self) -> int:
        return self._start_segment

    def segment_path(self, index: int) -> Path | None:
        if self._tmpdir is None:
            return None
        return self._tmpdir / f"seg-{index:05d}.ts"

    def current_segment_index(self) -> int:
        """Highest segment the current run has written contiguously from
        start_segment, or start_segment - 1 if none yet.

        Leftover segments from earlier runs (before a seek restart) share the
        temp dir, so a plain max() over the dir would overstate progress.
        """
        if self._tmpdir is None:
            return -1
        n = self._start_segment
        while True:
            try:
                if self.segment_path(n).stat().st_size == 0:
                    break
            except FileNotFoundError:
                break
            n += 1
        return n - 1

    async def start(
        self,
        input_path: Path,
        *,
        copy_video: bool,
        transcode_audio: bool,
        seek_to: float = 0.0,
        start_segment: int = 0,
    ) -> None:
        """Start (or restart) ffmpeg writing into the temp dir."""
        await self.stop()

        if self._tmpdir is None:
            self._tmpdir = Path(tempfile.mkdtemp(prefix="vc-hls-"))

        self._start_segment = start_segment

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]
        if seek_to > 0:
            cmd += ["-ss", str(seek_to)]
        # Cap input rate only when re-encoding; copy is cheap and full speed
        # lets the segment buffer fill quickly. The initial burst encodes the
        # first 30s at full speed so the receiver starts with a real buffer.
        if not copy_video:
            cmd += ["-readrate", "1.5", "-readrate_initial_burst", "30"]
            if platform.system() == "Darwin":
                # Decode on the GPU and keep frames there for the hw encoder.
                cmd += ["-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox_vld"]
        # -sn: sparse subtitle streams stall -readrate pacing below realtime.
        cmd += ["-i", str(input_path), "-sn"]

        if copy_video:
            # No re-encode. Segment splits at existing keyframes; the
            # orchestrator pre-probed them and synthesized a matching playlist.
            cmd += ["-c:v", "copy"]
        elif platform.system() == "Darwin":
            cmd += [
                "-c:v", "h264_videotoolbox",
                "-b:v", "6000k",
                "-prio_speed", "1",
                "-force_key_frames",
                f"expr:gte(t,n_forced*{HLS_SEGMENT_DURATION})",
            ]
        else:
            cmd += [
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "22",
                "-force_key_frames",
                f"expr:gte(t,n_forced*{HLS_SEGMENT_DURATION})",
            ]

        if transcode_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
        else:
            cmd += ["-c:a", "copy"]

        cmd += [
            "-f", "hls",
            "-hls_time", str(HLS_SEGMENT_DURATION),
            "-hls_list_size", "0",
            "-hls_flags", "independent_segments+omit_endlist+temp_file",
            "-hls_segment_type", "mpegts",
            "-hls_segment_filename", str(self._tmpdir / "seg-%05d.ts"),
            "-start_number", str(start_segment),
            str(self._tmpdir / "ffmpeg.m3u8"),
        ]

        log.info("Starting FFmpeg (HLS): %s", " ".join(cmd))
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        await self._wait_for_first_segment(timeout=30.0)

    def real_segment_duration(self) -> float:
        """Read first EXTINF from ffmpeg's playlist; fall back to nominal."""
        if self._tmpdir is None:
            return HLS_SEGMENT_DURATION
        playlist = self._tmpdir / "ffmpeg.m3u8"
        if not playlist.exists():
            return HLS_SEGMENT_DURATION
        try:
            for line in playlist.read_text().splitlines():
                if line.startswith("#EXTINF:"):
                    val = line.split(":", 1)[1].rstrip(",").strip()
                    return float(val)
        except (OSError, ValueError):
            pass
        return HLS_SEGMENT_DURATION

    async def _drain_stderr(self) -> None:
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        try:
            async for line in proc.stderr:
                text = line.decode(errors="replace").rstrip()
                if text:
                    log.warning("ffmpeg(hls): %s", text)
        except asyncio.CancelledError:
            pass

    async def _wait_for_first_segment(self, timeout: float) -> None:
        target = self.segment_path(self._start_segment)
        elapsed = 0.0
        while elapsed < timeout:
            if target and target.exists() and target.stat().st_size > 0:
                return
            if self._process and self._process.returncode is not None:
                raise RuntimeError(
                    f"ffmpeg exited before producing first HLS segment "
                    f"(rc={self._process.returncode})"
                )
            await asyncio.sleep(0.1)
            elapsed += 0.1
        log.warning(
            "First HLS segment %s did not appear in %.1fs", target, timeout
        )

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.kill()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        self._process = None
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None

    async def cleanup(self) -> None:
        await self.stop()
        if self._tmpdir and self._tmpdir.exists():
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        self._tmpdir = None

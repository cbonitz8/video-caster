"""HLS for one cast: plans the segment grid once and runs ffmpeg to fill it."""

from __future__ import annotations

import asyncio
import logging
import math
import platform
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from video_caster.transcoding.probe import ProbeResult, probe_keyframes as _probe_keyframes

log = logging.getLogger(__name__)

HLS_SEGMENT_DURATION = 6.0
FAR_SEEK_THRESHOLD = 5
SEGMENT_TIMEOUT = 30.0
POLL_INTERVAL = 0.1
SEGMENT_NAME_RE = re.compile(r"^seg-(\d{5})\.ts$")


@dataclass(frozen=True)
class SegmentGrid:
    starts: tuple[float, ...]
    duration: float

    def __len__(self) -> int:
        return len(self.starts)

    def durations(self) -> list[float]:
        ends = self.starts[1:] + (self.duration,)
        return [end - start for start, end in zip(self.starts, ends)]

    def cut_times_after(self, index: int) -> list[float]:
        base = self.starts[index]
        return [start - base for start in self.starts[index + 1:]]

    def playlist(self) -> str:
        durations = self.durations()
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{math.ceil(max(durations))}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
            "#EXT-X-INDEPENDENT-SEGMENTS",
        ]
        for index, duration in enumerate(durations):
            lines.append(f"#EXTINF:{duration:.6f},")
            lines.append(segment_name(index))
        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"


def segment_name(index: int) -> str:
    return f"seg-{index:05d}.ts"


def keyframe_grid(
    keyframes: list[float], duration: float, target: float = HLS_SEGMENT_DURATION
) -> SegmentGrid | None:
    if not keyframes:
        return None
    starts = [keyframes[0] if keyframes[0] < 0.5 else 0.0]
    for keyframe in keyframes[1:]:
        if keyframe >= len(starts) * target and keyframe < duration:
            starts.append(keyframe)
    return SegmentGrid(tuple(starts), duration)


def uniform_grid(duration: float, target: float = HLS_SEGMENT_DURATION) -> SegmentGrid:
    count = math.ceil(duration / target)
    return SegmentGrid(tuple(k * target for k in range(count)), duration)


SEGMENT_LIST = "segments.txt"


def ffmpeg_command(
    source: Path,
    grid: SegmentGrid,
    first: int,
    out_dir: Path,
    *,
    copy_video: bool,
    transcode_audio: bool,
    frame_rate: float | None,
) -> list[str]:
    half_frame = 0.5 / frame_rate if frame_rate else 0.0
    # A copy seek snaps back to the keyframe at or before -ss; aiming half a frame past the
    # planned keyframe keeps float rounding from snapping to the keyframe before it.
    base = grid.starts[first] + (half_frame if copy_video else 0.0)
    cuts = [t - (base - grid.starts[first]) for t in grid.cut_times_after(first)]

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]
    if base > 0:
        cmd += ["-ss", f"{base:.6f}"]
    if not copy_video:
        cmd += ["-readrate", "1.5", "-readrate_initial_burst", "30"]
        if platform.system() == "Darwin":
            cmd += ["-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox_vld"]
    # -sn: sparse subtitle streams stall -readrate pacing below realtime.
    cmd += ["-i", str(source), "-sn"]

    if copy_video:
        cmd += ["-c:v", "copy"]
    else:
        if platform.system() == "Darwin":
            cmd += ["-c:v", "h264_videotoolbox", "-b:v", "6000k", "-prio_speed", "1"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]
        if cuts:
            cmd += ["-force_key_frames", ",".join(f"{t:.6f}" for t in cuts)]

    if transcode_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
    else:
        cmd += ["-c:a", "copy"]

    if base > 0:
        cmd += ["-output_ts_offset", f"{base:.6f}"]
    cmd += ["-f", "segment", "-segment_format", "mpegts", "-reset_timestamps", "0"]
    if cuts:
        # Cut half a frame early: the muxer cuts at the first keyframe at or after each time,
        # and rounding can put the planned keyframe a hair before its exact time.
        cmd += ["-segment_times", ",".join(f"{t - half_frame:.6f}" for t in cuts)]
    cmd += [
        "-segment_start_number", str(first),
        "-segment_list", str(out_dir / SEGMENT_LIST),
        "-segment_list_type", "flat",
        str(out_dir / "seg-%05d.ts"),
    ]
    return cmd


class HlsStartTimeout(Exception):
    pass


class FfmpegProcess(Protocol):
    returncode: int | None

    def kill(self) -> None: ...

    async def wait(self) -> int: ...


Spawn = Callable[[list[str]], Awaitable[FfmpegProcess]]
ProbeKeyframes = Callable[[Path], Awaitable[list[float]]]


class _Ffmpeg:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self._stderr = asyncio.create_task(self._drain_stderr())

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    def kill(self) -> None:
        self._process.kill()

    async def wait(self) -> int:
        code = await self._process.wait()
        self._stderr.cancel()
        return code

    async def _drain_stderr(self) -> None:
        assert self._process.stderr is not None
        async for line in self._process.stderr:
            text = line.decode(errors="replace").rstrip()
            if text:
                log.warning("ffmpeg(hls): %s", text)


async def spawn_ffmpeg(cmd: list[str]) -> FfmpegProcess:
    log.info("Starting FFmpeg (HLS): %s", " ".join(cmd))
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    return _Ffmpeg(process)


@dataclass
class _Run:
    first: int
    dir: Path
    process: FfmpegProcess
    listed: int = 0

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    def frontier(self) -> int:
        return self.first + self.listed - 1


class HlsSession:
    def __init__(self, source: Path, grid: SegmentGrid, *, copy_video: bool,
                 transcode_audio: bool, frame_rate: float | None, spawn: Spawn,
                 timeout: float) -> None:
        self._source = source
        self._grid = grid
        self.copy_video = copy_video
        self._transcode_audio = transcode_audio
        self._frame_rate = frame_rate
        self._spawn = spawn
        self._timeout = timeout
        self._dir = Path(tempfile.mkdtemp(prefix="vc-hls-"))
        self._ready: dict[int, Path] = {}
        self._run: _Run | None = None
        self._runs_started = 0
        self._lock = asyncio.Lock()
        self._closed = False

    @classmethod
    async def open(
        cls,
        source: Path,
        probed: ProbeResult,
        *,
        copy_video: bool,
        transcode_audio: bool,
        spawn: Spawn = spawn_ffmpeg,
        probe_keyframes: ProbeKeyframes = _probe_keyframes,
        timeout: float = SEGMENT_TIMEOUT,
    ) -> HlsSession:
        grid = None
        if copy_video:
            grid = keyframe_grid(await probe_keyframes(source), probed.duration)
            if grid is None:
                log.warning("Keyframe probe returned nothing for %s; falling back to re-encode",
                            source.name)
                copy_video = False
        if grid is None:
            grid = uniform_grid(probed.duration)
        if len(grid) == 0:
            raise ValueError(f"Can't stream {source.name} as HLS: its duration is unknown")
        if probed.frame_rate is None:
            log.warning("No usable frame rate for %s; segment cuts are not nudged", source.name)

        session = cls(source, grid, copy_video=copy_video, transcode_audio=transcode_audio,
                      frame_rate=probed.frame_rate, spawn=spawn, timeout=timeout)
        try:
            await session._start_run(0)
            if await session._wait_for(0, session._run) is None:
                session._raise_start_failure()
        except BaseException:
            await session.close()
            raise
        return session

    def playlist(self) -> str:
        return self._grid.playlist()

    async def segment(self, index: int) -> Path | None:
        async with self._lock:
            if self._closed:
                return None
            self._refresh()
            if index in self._ready:
                return self._ready[index]
            if not 0 <= index < len(self._grid):
                return None
            if not self._run_will_reach(index):
                log.info("HLS far seek to seg %d (%.1fs); restarting ffmpeg",
                         index, self._grid.starts[index])
                await self._start_run(index)
            run = self._run
        return await self._wait_for(index, run)

    async def close(self) -> None:
        self._closed = True
        await self._stop_run()
        shutil.rmtree(self._dir, ignore_errors=True)

    def _raise_start_failure(self) -> None:
        code = self._run.process.returncode
        if code is not None:
            raise RuntimeError(f"ffmpeg exited before producing first HLS segment (rc={code})")
        raise HlsStartTimeout(f"no video from ffmpeg after {self._timeout:.0f}s")

    def _run_will_reach(self, index: int) -> bool:
        run = self._run
        return run.alive and run.first <= index <= run.frontier() + FAR_SEEK_THRESHOLD

    async def _start_run(self, first: int) -> None:
        await self._stop_run()
        run_dir = self._dir / f"run-{self._runs_started:03d}"
        self._runs_started += 1
        run_dir.mkdir()
        cmd = ffmpeg_command(self._source, self._grid, first, run_dir,
                             copy_video=self.copy_video, transcode_audio=self._transcode_audio,
                             frame_rate=self._frame_rate)
        self._run = _Run(first, run_dir, await self._spawn(cmd))

    async def _stop_run(self) -> None:
        run = self._run
        if run is None:
            return
        self._refresh()
        if run.alive:
            run.process.kill()
            try:
                await asyncio.wait_for(run.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                log.warning("ffmpeg(hls) didn't exit within 2s of kill")

    def _refresh(self) -> None:
        run = self._run
        if run is None:
            return
        try:
            text = (run.dir / SEGMENT_LIST).read_text()
        except FileNotFoundError:
            return
        complete_lines = text.split("\n")[:-1]
        for name in complete_lines[run.listed:]:
            match = SEGMENT_NAME_RE.match(name)
            if match is None:
                log.warning("Unexpected entry in ffmpeg segment list: %r", name)
                continue
            self._ready.setdefault(int(match.group(1)), run.dir / name)
        run.listed = len(complete_lines)

    async def _wait_for(self, index: int, run: _Run) -> Path | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while not self._closed:
            if run is self._run:
                self._refresh()
            if index in self._ready:
                return self._ready[index]
            if not run.alive or run is not self._run or loop.time() >= deadline:
                return None
            await asyncio.sleep(POLL_INTERVAL)
        return None

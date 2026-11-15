from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from video_caster.transcoding.hls import (
    HlsSession, HlsStartTimeout, ffmpeg_command, keyframe_grid, uniform_grid,
)
from video_caster.transcoding.probe import ProbeResult, frame_rate_of, probe, probe_keyframes


def test_keyframe_grid_starts_each_segment_at_the_first_keyframe_past_each_six_seconds():
    keyframes = [i * 2.5 for i in range(9)]
    grid = keyframe_grid(keyframes, 22.0)
    assert grid.starts == (0.0, 7.5, 12.5, 20.0)
    assert grid.durations() == [7.5, 5.0, 7.5, 2.0]


def test_keyframe_grid_over_a_whole_episode_sums_to_its_duration():
    keyframes = [i * 2.5 for i in range(240)]
    grid = keyframe_grid(keyframes, 600.0)
    assert len(grid) == 100
    assert sum(grid.durations()) == pytest.approx(600.0)


def test_keyframe_grid_matches_ffmpeg_on_a_real_episode():
    # First 40s of Ted Lasso S04E07: ffprobe keyframes, and the segment starts that
    # `ffmpeg -c:v copy -f hls -hls_time 6` actually wrote for that file.
    keyframes = [0.0, 3.629, 7.257, 10.928, 13.597, 16.308, 17.976, 19.061, 20.354, 21.688,
                 23.065, 24.858, 26.818, 28.111, 30.322, 32.574, 34.326, 35.661, 37.204, 39.498]
    grid = keyframe_grid(keyframes, 40.0)
    assert grid.starts == (0.0, 7.257, 13.597, 19.061, 24.858, 30.322, 37.204)


def test_no_keyframes_means_no_keyframe_grid():
    assert keyframe_grid([], 40.0) is None


def test_uniform_grid_ends_with_the_remainder():
    grid = uniform_grid(14.5)
    assert grid.starts == (0.0, 6.0, 12.0)
    assert grid.durations() == [6.0, 6.0, 2.5]


def test_cut_times_after_a_segment_are_relative_to_its_start():
    grid = keyframe_grid([0.0, 7.257, 13.597, 19.061], 22.0)
    assert grid.cut_times_after(1) == pytest.approx([6.34, 11.804])
    assert grid.cut_times_after(3) == []


def test_playlist_lists_every_planned_segment_as_vod():
    grid = keyframe_grid([0.0, 7.25, 13.5], 20.0)
    assert grid.playlist() == (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:8\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n"
        "#EXT-X-INDEPENDENT-SEGMENTS\n"
        "#EXTINF:7.250000,\n"
        "seg-00000.ts\n"
        "#EXTINF:6.250000,\n"
        "seg-00001.ts\n"
        "#EXTINF:6.500000,\n"
        "seg-00002.ts\n"
        "#EXT-X-ENDLIST\n"
    )


@pytest.mark.parametrize("stream, expected", [
    ({"r_frame_rate": "24000/1001", "avg_frame_rate": "24000/1001"}, 24000 / 1001),
    ({"r_frame_rate": "0/0", "avg_frame_rate": "25/1"}, 25.0),
    ({"r_frame_rate": "1000/1", "avg_frame_rate": "30000/1001"}, 30000 / 1001),
    ({"r_frame_rate": "0/0", "avg_frame_rate": "0/0"}, None),
    ({}, None),
])
def test_frame_rate_prefers_r_frame_rate_and_rejects_absurd_values(stream, expected):
    assert frame_rate_of(stream) == (pytest.approx(expected) if expected else None)


@pytest.fixture(scope="module")
def irregular_clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg not on PATH")
    path = tmp_path_factory.mktemp("clip") / "irregular.mp4"
    keyframes = "0,2.1,6.4,8.0,13.3,15.9,19.2,24.7,26.1,31.5,33.0,38.8"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24000/1001",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", "42", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-x264-params", "keyint=1000:min-keyint=1000:scenecut=0",
         "-force_key_frames", keyframes, "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path


def first_video_pts(segment: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", "-read_intervals", "%+#1", str(segment)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.split()[0].rstrip(","))


def encode(source, grid, first, out_dir, copy_video, frame_rate) -> dict[int, float]:
    out_dir.mkdir()
    subprocess.run(
        ffmpeg_command(source, grid, first, out_dir, copy_video=copy_video,
                       transcode_audio=True, frame_rate=frame_rate),
        check=True,
    )
    listed = (out_dir / "segments.txt").read_text().split()
    return {int(name[4:9]): first_video_pts(out_dir / name) for name in listed}


@pytest.mark.parametrize("copy_video", [True, False], ids=["copy", "re-encode"])
async def test_a_restart_at_segment_i_lands_on_the_full_runs_grid(irregular_clip, tmp_path, copy_video):
    probed = await probe(irregular_clip)
    if copy_video:
        grid = keyframe_grid(await probe_keyframes(irregular_clip), probed.duration)
    else:
        grid = uniform_grid(probed.duration)
    restart_at = 3

    full = encode(irregular_clip, grid, 0, tmp_path / "full", copy_video, probed.frame_rate)
    restarted = encode(irregular_clip, grid, restart_at, tmp_path / "restart", copy_video,
                       probed.frame_rate)

    assert sorted(full) == list(range(len(grid)))
    assert sorted(restarted) == list(range(restart_at, len(grid)))
    one_frame = 1 / probed.frame_rate
    for index, pts in restarted.items():
        assert pts == pytest.approx(full[index], abs=one_frame), index


class FakeRun:
    def __init__(self, cmd: list[str]) -> None:
        self.cmd = cmd
        self.returncode: int | None = None
        self.dir = Path(self.arg("-segment_list")).parent
        self.first = int(self.arg("-segment_start_number"))

    def arg(self, name: str) -> str:
        return self.cmd[self.cmd.index(name) + 1]

    def has(self, name: str) -> bool:
        return name in self.cmd

    def write(self, *indexes: int) -> None:
        for index in indexes:
            (self.dir / f"seg-{index:05d}.ts").write_bytes(b"ts")
            with (self.dir / "segments.txt").open("a") as listed:
                listed.write(f"seg-{index:05d}.ts\n")

    def write_unlisted(self, index: int) -> None:
        (self.dir / f"seg-{index:05d}.ts").write_bytes(b"half")

    def exit(self, code: int = 0) -> None:
        self.returncode = code

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode


class FakeFfmpeg:
    def __init__(self, writes_first: bool = True, exits_at_once: int | None = None) -> None:
        self.runs: list[FakeRun] = []
        self.writes_first = writes_first
        self.exits_at_once = exits_at_once

    async def __call__(self, cmd: list[str]) -> FakeRun:
        run = FakeRun(cmd)
        self.runs.append(run)
        if self.exits_at_once is not None:
            run.exit(self.exits_at_once)
        elif self.writes_first:
            run.write(run.first)
        return run


KEYFRAMES = [0.0, 7.257, 13.597, 19.061, 24.858, 30.322, 37.204, 43.0, 49.5, 55.1, 61.2]


async def open_session(ffmpeg, copy_video=True, timeout=0.3) -> HlsSession:
    async def keyframes(path):
        return KEYFRAMES

    probed = ProbeResult(video_codec="h264", duration=64.0, frame_rate=25.0)
    return await HlsSession.open(Path("Show.mkv"), probed, copy_video=copy_video,
                                 transcode_audio=True, spawn=ffmpeg, probe_keyframes=keyframes,
                                 timeout=timeout)


async def test_open_serves_the_planned_playlist_once_segment_zero_is_written():
    session = await open_session(FakeFfmpeg())
    try:
        assert session.playlist() == keyframe_grid(KEYFRAMES, 64.0).playlist()
        assert (await session.segment(0)).read_bytes() == b"ts"
    finally:
        await session.close()


async def test_a_segment_is_served_only_once_ffmpeg_lists_it():
    ffmpeg = FakeFfmpeg()
    session = await open_session(ffmpeg)
    try:
        [run] = ffmpeg.runs
        run.write_unlisted(1)
        waiting = asyncio.create_task(session.segment(1))
        await asyncio.sleep(0.15)
        assert not waiting.done()
        run.write(1)
        assert (await waiting).name == "seg-00001.ts"
        assert len(ffmpeg.runs) == 1
    finally:
        await session.close()


async def test_a_segment_just_ahead_of_the_encode_waits_without_restarting():
    ffmpeg = FakeFfmpeg()
    session = await open_session(ffmpeg)
    try:
        [run] = ffmpeg.runs
        waiting = asyncio.create_task(session.segment(5))
        await asyncio.sleep(0.05)
        run.write(1, 2, 3, 4, 5)
        assert (await waiting).name == "seg-00005.ts"
        assert len(ffmpeg.runs) == 1
    finally:
        await session.close()


async def test_a_far_seek_restarts_ffmpeg_on_the_planned_grid():
    ffmpeg = FakeFfmpeg()
    session = await open_session(ffmpeg)
    try:
        first = ffmpeg.runs[0]
        assert await session.segment(8) is not None
        assert first.returncode == -9
        restart = ffmpeg.runs[1]
        assert restart.first == 8
        assert float(restart.arg("-ss")) == pytest.approx(49.5 + 0.02)
        assert float(restart.arg("-output_ts_offset")) == pytest.approx(49.52)
        cuts = [float(t) for t in restart.arg("-segment_times").split(",")]
        assert cuts == pytest.approx([55.1 - 49.5 - 0.04, 61.2 - 49.5 - 0.04])
    finally:
        await session.close()


async def test_segments_from_an_earlier_run_are_still_served_after_a_restart():
    ffmpeg = FakeFfmpeg()
    session = await open_session(ffmpeg)
    try:
        ffmpeg.runs[0].write(1, 2)
        await session.segment(9)
        assert (await session.segment(2)).read_bytes() == b"ts"
        assert len(ffmpeg.runs) == 2
    finally:
        await session.close()


async def test_a_seek_back_before_the_current_run_restarts_there():
    ffmpeg = FakeFfmpeg()
    session = await open_session(ffmpeg)
    try:
        await session.segment(9)
        assert await session.segment(3) is not None
        assert [run.first for run in ffmpeg.runs] == [0, 9, 3]
    finally:
        await session.close()


async def test_a_segment_past_the_grid_is_not_found():
    ffmpeg = FakeFfmpeg()
    session = await open_session(ffmpeg)
    try:
        assert await session.segment(11) is None
        assert len(ffmpeg.runs) == 1
    finally:
        await session.close()


async def test_a_segment_the_dead_run_never_wrote_fails_at_once():
    ffmpeg = FakeFfmpeg()
    session = await open_session(ffmpeg, timeout=5.0)
    try:
        waiting = asyncio.create_task(session.segment(2))
        await asyncio.sleep(0.05)
        ffmpeg.runs[0].exit(1)
        assert await asyncio.wait_for(waiting, timeout=1.0) is None
    finally:
        await session.close()


async def test_a_segment_that_never_arrives_times_out():
    ffmpeg = FakeFfmpeg()
    session = await open_session(ffmpeg, timeout=0.2)
    try:
        assert await session.segment(1) is None
    finally:
        await session.close()


async def test_open_times_out_without_segment_zero_and_cleans_up():
    ffmpeg = FakeFfmpeg(writes_first=False)
    with pytest.raises(HlsStartTimeout):
        await open_session(ffmpeg, timeout=0.2)
    [run] = ffmpeg.runs
    assert run.returncode == -9
    assert not run.dir.exists()


async def test_open_fails_when_ffmpeg_exits_before_segment_zero():
    ffmpeg = FakeFfmpeg(exits_at_once=1)
    with pytest.raises(RuntimeError, match="rc=1"):
        await open_session(ffmpeg, timeout=5.0)
    assert not ffmpeg.runs[0].dir.exists()


async def test_no_keyframes_falls_back_to_a_reencode_on_the_uniform_grid():
    ffmpeg = FakeFfmpeg()

    async def no_keyframes(path):
        return []

    probed = ProbeResult(video_codec="h264", duration=14.5, frame_rate=25.0)
    session = await HlsSession.open(Path("Show.mkv"), probed, copy_video=True,
                                    transcode_audio=False, spawn=ffmpeg,
                                    probe_keyframes=no_keyframes, timeout=0.3)
    try:
        assert not session.copy_video
        assert session.playlist() == uniform_grid(14.5).playlist()
        assert ffmpeg.runs[0].arg("-c:v") != "copy"
    finally:
        await session.close()


async def test_close_ends_a_pending_segment_wait():
    ffmpeg = FakeFfmpeg()
    session = await open_session(ffmpeg, timeout=5.0)
    waiting = asyncio.create_task(session.segment(1))
    await asyncio.sleep(0.05)
    await session.close()
    assert await asyncio.wait_for(waiting, timeout=1.0) is None

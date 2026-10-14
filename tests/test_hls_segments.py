from __future__ import annotations

import pytest

from video_caster.transcoding.probe import group_keyframes_into_segments


def starts(segments):
    return [start for start, _ in segments]


def test_cuts_follow_ffmpegs_fixed_grid_from_stream_start():
    keyframes = [i * 2.5 for i in range(9)]  # 0, 2.5 … 20
    segments = group_keyframes_into_segments(keyframes, 22.0, 6.0)
    assert starts(segments) == [0.0, 7.5, 12.5, 20.0]


def test_segment_count_matches_ffmpeg_over_a_whole_episode():
    keyframes = [i * 2.5 for i in range(240)]  # 600s of video
    segments = group_keyframes_into_segments(keyframes, 600.0, 6.0)
    assert len(segments) == 100
    assert sum(d for _, d in segments) == pytest.approx(600.0)


def test_cuts_match_ffmpeg_on_a_real_episode():
    # First 40s of Ted Lasso S04E07: ffprobe keyframes, and the segment starts that
    # `ffmpeg -c:v copy -f hls -hls_time 6` actually wrote for that file.
    keyframes = [0.0, 3.629, 7.257, 10.928, 13.597, 16.308, 17.976, 19.061, 20.354, 21.688,
                 23.065, 24.858, 26.818, 28.111, 30.322, 32.574, 34.326, 35.661, 37.204, 39.498]
    segments = group_keyframes_into_segments(keyframes, 40.0, 6.0)
    assert starts(segments) == [0.0, 7.257, 13.597, 19.061, 24.858, 30.322, 37.204]

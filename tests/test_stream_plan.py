from __future__ import annotations

import pytest

from video_caster.casting.stream_plan import Direct, Hls, Pipe, capabilities_for, choose_plan
from video_caster.discovery.device import DeviceType
from video_caster.transcoding.probe import ProbeResult

CC = DeviceType.CHROMECAST
ATV = DeviceType.APPLETV
DLNA = DeviceType.DLNA


def hls(video: bool, audio: bool) -> Hls:
    return Hls(transcode_video=video, transcode_audio=audio)


def pipe(video: bool, audio: bool) -> Pipe:
    return Pipe(transcode_video=video, transcode_audio=audio)


ROWS = [
    (CC, "h264", "aac", "mp4", 2, Direct()),
    (CC, "h264", "aac", "mp4", 6, hls(False, True)),
    (CC, "h264", "aac", "mkv", 2, Direct()),
    (CC, "hevc", "aac", "mkv", 2, hls(True, False)),
    (CC, "h264", "ac3", "mkv", 6, hls(False, True)),
    (CC, "h264", "eac3", "mkv", 6, hls(False, True)),
    (CC, "h264", "dts", "mkv", 6, hls(False, True)),
    (CC, "hevc", "eac3", "mp4", 6, hls(True, True)),
    (CC, "vp9", "opus", "webm", 2, Direct()),
    (CC, "mpeg4", "mp3", "avi", 2, hls(True, False)),
    (CC, "h264", "flac", "mkv", 2, Direct()),
    (CC, "h264", "truehd", "mkv", 8, hls(False, True)),
    (CC, "h264", "aac", "mov", 2, hls(False, False)),
    (ATV, "h264", "aac", "mp4", 2, Direct()),
    (ATV, "h264", "aac", "mp4", 6, Direct()),
    (ATV, "h264", "aac", "mkv", 2, hls(False, False)),
    (ATV, "hevc", "aac", "mkv", 2, hls(True, False)),
    (ATV, "h264", "ac3", "mkv", 6, hls(False, False)),
    (ATV, "h264", "eac3", "mkv", 6, hls(False, True)),
    (ATV, "h264", "dts", "mkv", 6, hls(False, True)),
    (ATV, "hevc", "eac3", "mp4", 6, hls(True, True)),
    (ATV, "vp9", "opus", "webm", 2, hls(True, True)),
    (ATV, "mpeg4", "mp3", "avi", 2, hls(True, False)),
    (ATV, "h264", "flac", "mkv", 2, hls(False, False)),
    (ATV, "h264", "truehd", "mkv", 8, hls(False, True)),
    (ATV, "h264", "aac", "mov", 2, Direct()),
    (DLNA, "h264", "aac", "mp4", 2, Direct()),
    (DLNA, "h264", "aac", "mp4", 6, pipe(False, True)),
    (DLNA, "h264", "aac", "mkv", 2, pipe(False, False)),
    (DLNA, "hevc", "aac", "mkv", 2, pipe(True, False)),
    (DLNA, "h264", "ac3", "mkv", 6, pipe(False, True)),
    (DLNA, "h264", "eac3", "mkv", 6, pipe(False, True)),
    (DLNA, "h264", "dts", "mkv", 6, pipe(False, True)),
    (DLNA, "hevc", "eac3", "mp4", 6, pipe(True, True)),
    (DLNA, "vp9", "opus", "webm", 2, pipe(True, True)),
    (DLNA, "mpeg4", "mp3", "avi", 2, pipe(True, False)),
    (DLNA, "h264", "flac", "mkv", 2, pipe(False, True)),
    (DLNA, "h264", "truehd", "mkv", 8, pipe(False, True)),
    (DLNA, "h264", "aac", "mov", 2, pipe(False, False)),
]


@pytest.mark.parametrize("device_type, video, audio, container, channels, expected", ROWS)
def test_plan_for_each_device_type_and_codec_mix(device_type, video, audio, container, channels, expected):
    probed = ProbeResult(video_codec=video, audio_codec=audio, container=container,
                         audio_channels=channels, duration=60.0)
    assert choose_plan(probed, capabilities_for(device_type)) == expected


def test_codec_names_are_case_insensitive():
    probed = ProbeResult(video_codec="H264", audio_codec="AAC", container="MP4", audio_channels=2)
    assert choose_plan(probed, capabilities_for(CC)) == Direct()


def test_an_unknown_device_type_has_no_capabilities():
    with pytest.raises(ValueError):
        capabilities_for("roku")

"""Codec/container compatibility tables for Chromecast and AirPlay."""

from __future__ import annotations

# Video codecs natively supported (no transcoding needed)
CHROMECAST_VIDEO_CODECS = {"h264", "vp8", "vp9", "av1"}
AIRPLAY_VIDEO_CODECS = {"h264"}  # HEVC over AirPlay is unreliable — always transcode

# Audio codecs natively supported
CHROMECAST_AUDIO_CODECS = {"aac", "mp3", "flac", "opus", "vorbis", "ac3", "eac3"}
AIRPLAY_AUDIO_CODECS = {"aac", "mp3", "flac", "alac", "ac3"}

# Containers that can be served directly (no remux needed)
CHROMECAST_CONTAINERS = {"mp4", "webm", "mkv"}
AIRPLAY_CONTAINERS = {"mp4", "mov"}

# DLNA — conservative defaults for maximum renderer compatibility
DLNA_VIDEO_CODECS = {"h264"}
DLNA_AUDIO_CODECS = {"aac", "mp3", "ac3"}
DLNA_CONTAINERS = {"mp4"}

# Video file extensions we recognize
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v",
    ".wmv", ".flv", ".ts", ".mts", ".m2ts", ".ogv",
    ".3gp", ".mpg", ".mpeg",
}

# Target transcode settings
TRANSCODE_VIDEO_CODEC = "libx264"
TRANSCODE_AUDIO_CODEC = "aac"
TRANSCODE_CONTAINER = "mp4"


def needs_transcode(
    video_codec: str,
    audio_codec: str,
    container: str,
    target: str,
) -> tuple[bool, bool, bool]:
    """Check if transcoding is needed for the given target device type.

    Returns (needs_video_transcode, needs_audio_transcode, needs_remux).
    """
    video_codec = video_codec.lower()
    audio_codec = audio_codec.lower()
    container = container.lower()

    if target == "chromecast":
        supported_video = CHROMECAST_VIDEO_CODECS
        supported_audio = CHROMECAST_AUDIO_CODECS
        supported_containers = CHROMECAST_CONTAINERS
    elif target == "dlna":
        supported_video = DLNA_VIDEO_CODECS
        supported_audio = DLNA_AUDIO_CODECS
        supported_containers = DLNA_CONTAINERS
    else:  # appletv / airplay
        supported_video = AIRPLAY_VIDEO_CODECS
        supported_audio = AIRPLAY_AUDIO_CODECS
        supported_containers = AIRPLAY_CONTAINERS

    video_ok = video_codec in supported_video
    audio_ok = audio_codec in supported_audio
    container_ok = container in supported_containers

    needs_video = not video_ok
    needs_audio = not audio_ok
    needs_remux = not container_ok and video_ok and audio_ok

    return needs_video, needs_audio, needs_remux

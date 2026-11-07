"""Async ffprobe wrapper for extracting media file information."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class ProbeResult:
    video_codec: str = ""
    audio_codec: str = ""
    container: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    audio_channels: int = 0


async def probe(path: Path) -> ProbeResult:
    """Run ffprobe on a file and return parsed media info."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        log.error("ffprobe failed for %s: %s", path, stderr.decode())
        return ProbeResult()

    data = json.loads(stdout)
    result = ProbeResult()

    # Extract container from format
    fmt = data.get("format", {})
    format_name = fmt.get("format_name", "")
    result.duration = float(fmt.get("duration", 0))

    # Map ffprobe format names to simpler container names
    if "mp4" in format_name or "m4v" in format_name or "mov" in format_name:
        result.container = "mp4"
    elif "matroska" in format_name or "webm" in format_name:
        if "webm" in format_name:
            result.container = "webm"
        else:
            result.container = "mkv"
    elif "avi" in format_name:
        result.container = "avi"
    else:
        result.container = format_name.split(",")[0]

    # Extract stream info
    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type", "")
        codec_name = stream.get("codec_name", "")

        if codec_type == "video" and not result.video_codec:
            result.video_codec = codec_name
            result.width = int(stream.get("width", 0))
            result.height = int(stream.get("height", 0))
        elif codec_type == "audio" and not result.audio_codec:
            result.audio_codec = codec_name
            result.audio_channels = int(stream.get("channels", 0))

    log.info(
        "Probed %s: video=%s audio=%s/%dch container=%s duration=%.1fs",
        path.name, result.video_codec, result.audio_codec,
        result.audio_channels, result.container, result.duration,
    )
    return result


async def probe_keyframes(path: Path) -> list[float]:
    """Return video keyframe timestamps (seconds) in order."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "packet=pts_time,flags",
        "-of", "csv=print_section=0",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.error("ffprobe keyframe scan failed for %s: %s", path, stderr.decode())
        return []

    keyframes: list[float] = []
    for line in stdout.decode().splitlines():
        # Format: "<pts_time>,<flags>" — flags string contains 'K' for keyframe
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        pts_str, flags = parts[0], parts[1]
        if "K" not in flags:
            continue
        try:
            keyframes.append(float(pts_str))
        except ValueError:
            continue
    return keyframes


def group_keyframes_into_segments(
    keyframes: list[float],
    total_duration: float,
    target_segment_duration: float,
) -> list[tuple[float, float]]:
    """Group keyframes into HLS-style segments of ~target_segment_duration.

    Returns a list of (start_time, duration) tuples. Mirrors what
    `ffmpeg -c:v copy -f hls -hls_time N` emits: segment k begins at the first
    keyframe at or after k * target, on a fixed grid from the stream start.
    """
    if not keyframes or total_duration <= 0:
        return []

    # Ensure we start at 0 even if first keyframe is slightly later (rare).
    starts: list[float] = [keyframes[0] if keyframes[0] < 0.5 else 0.0]
    for kf in keyframes[1:]:
        if kf >= len(starts) * target_segment_duration:
            starts.append(kf)

    segments: list[tuple[float, float]] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else total_duration
        duration = end - start
        if duration > 0:
            segments.append((start, duration))
    return segments

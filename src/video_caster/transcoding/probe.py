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
    frame_rate: float | None = None


def frame_rate_of(stream: dict) -> float | None:
    """r_frame_rate, else avg_frame_rate; VFR files often report 0/0 or 1000/1 for r_frame_rate."""
    for key in ("r_frame_rate", "avg_frame_rate"):
        rate = _ratio(stream.get(key))
        if rate is not None and 1.0 <= rate <= 240.0:
            return rate
    return None


def _ratio(text: str | None) -> float | None:
    if text is None:
        return None
    numerator, _, denominator = text.partition("/")
    try:
        num, den = float(numerator), float(denominator)
    except ValueError:
        return None
    if den == 0:
        return None
    return num / den


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
            result.frame_rate = frame_rate_of(stream)
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

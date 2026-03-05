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

    log.info(
        "Probed %s: video=%s audio=%s container=%s duration=%.1fs",
        path.name, result.video_codec, result.audio_codec,
        result.container, result.duration,
    )
    return result

"""Video file browser using Textual's DirectoryTree."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import DirectoryTree

from video_caster.transcoding.formats import VIDEO_EXTENSIONS


class VideoBrowser(DirectoryTree):
    """A DirectoryTree filtered to show only video files and directories."""

    def filter_paths(self, paths: list[Path]) -> list[Path]:
        return [
            p for p in paths
            if p.is_dir() or p.suffix.lower() in VIDEO_EXTENSIONS
        ]

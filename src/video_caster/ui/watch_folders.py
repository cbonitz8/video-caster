"""Watch folder browser — one collapsible DirectoryTree per configured folder."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Collapsible, Label

from video_caster.ui.file_browser import VideoBrowser


class WatchFolderBrowser(Widget):
    """Displays a collapsible VideoBrowser for each watch folder."""

    DEFAULT_CSS = """
    WatchFolderBrowser {
        height: 1fr;
        padding: 0 1;
    }
    WatchFolderBrowser .no-folders {
        color: $text-muted;
        padding: 1;
    }
    """

    def __init__(self, folders: list[Path] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._folders = folders or []

    def compose(self) -> ComposeResult:
        if not self._folders:
            yield Label("No watch folders configured. Add them in Settings.", classes="no-folders")
            return
        for folder in self._folders:
            if folder.is_dir():
                yield Collapsible(
                    VideoBrowser(folder),
                    title=str(folder),
                    collapsed=len(self._folders) > 1,
                )

    def set_folders(self, folders: list[Path]) -> None:
        self._folders = folders
        self.recompose()

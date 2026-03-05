"""Home tab widgets: Continue Watching and Newly Added lists."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

from video_caster.storage.episode import find_next_episode
from video_caster.storage.history import WatchRecord
from video_caster.storage.scanner import VideoFileInfo

log = logging.getLogger(__name__)


def _format_progress_bar(progress: float, width: int = 20) -> str:
    filled = int(progress * width)
    return "[green]" + "=" * filled + "[/][dim]" + "-" * (width - filled) + "[/]"


class FileChosen(Message):
    """Posted when the user selects a file from Home tab lists."""
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__()


class ContinueWatchingList(Widget):
    """Shows partially-watched files with progress and next episode suggestion."""

    DEFAULT_CSS = """
    ContinueWatchingList {
        height: auto;
        padding: 0 1;
    }
    ContinueWatchingList .section-header {
        text-style: bold;
        color: $accent;
        padding: 1 0 0 0;
    }
    ContinueWatchingList .empty-msg {
        color: $text-muted;
        padding: 0 1;
    }
    ContinueWatchingList ListView {
        height: auto;
        max-height: 16;
    }
    """

    _record_count: reactive[int] = reactive(0, recompose=True)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._records: list[WatchRecord] = []

    def compose(self) -> ComposeResult:
        yield Label("Continue Watching", classes="section-header")
        if not self._records:
            yield Label("No watch history yet.", classes="empty-msg")
        else:
            yield ListView(
                *self._make_items(),
                id="continue-watching-list",
            )

    def _make_items(self) -> list[ListItem]:
        items = []
        for rec in self._records:
            pct = int(rec.progress * 100)
            bar = _format_progress_bar(rec.progress)
            text = f"  {rec.file_name}  {bar} {pct}%"
            item = ListItem(Label(text), name=rec.file_path)
            items.append(item)
            # Check for next episode
            path = Path(rec.file_path)
            next_ep = find_next_episode(path)
            if next_ep:
                items.append(
                    ListItem(
                        Label(f"    [dim]Next: {next_ep.name}[/]"),
                        name=str(next_ep),
                    )
                )
        return items

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = event.item.name
        if name:
            self.post_message(FileChosen(Path(name)))

    def set_records(self, records: list[WatchRecord]) -> None:
        self._records = records
        self._record_count = len(records)


@dataclass
class UpNextEntry:
    """A suggested next episode with context about what was watched."""
    next_path: Path
    next_name: str
    watched_name: str


class UpNextList(Widget):
    """Shows next episodes for completed/nearly-completed series episodes."""

    DEFAULT_CSS = """
    UpNextList {
        height: auto;
        padding: 0 1;
    }
    UpNextList .section-header {
        text-style: bold;
        color: $accent;
        padding: 1 0 0 0;
    }
    UpNextList .empty-msg {
        color: $text-muted;
        padding: 0 1;
    }
    UpNextList ListView {
        height: auto;
        max-height: 16;
    }
    """

    _entry_count: reactive[int] = reactive(0, recompose=True)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._entries: list[UpNextEntry] = []

    def compose(self) -> ComposeResult:
        yield Label("Up Next", classes="section-header")
        if not self._entries:
            yield Label("No upcoming episodes.", classes="empty-msg")
        else:
            yield ListView(
                *[
                    ListItem(
                        Label(f"  {e.next_name}  [dim]after {e.watched_name}[/]"),
                        name=str(e.next_path),
                    )
                    for e in self._entries
                ],
                id="up-next-list",
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = event.item.name
        if name:
            self.post_message(FileChosen(Path(name)))

    def set_entries(self, entries: list[UpNextEntry]) -> None:
        self._entries = entries
        self._entry_count = len(entries)


class NewlyAddedList(Widget):
    """Recently modified video files across watch folders."""

    DEFAULT_CSS = """
    NewlyAddedList {
        height: auto;
        padding: 0 1;
    }
    NewlyAddedList .section-header {
        text-style: bold;
        color: $accent;
        padding: 1 0 0 0;
    }
    NewlyAddedList .empty-msg {
        color: $text-muted;
        padding: 0 1;
    }
    NewlyAddedList ListView {
        height: auto;
        max-height: 16;
    }
    """

    _file_count: reactive[int] = reactive(0, recompose=True)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files: list[VideoFileInfo] = []

    def compose(self) -> ComposeResult:
        yield Label("Newly Added", classes="section-header")
        if not self._files:
            yield Label("No files found. Add watch folders in Settings.", classes="empty-msg")
        else:
            yield ListView(
                *[
                    ListItem(
                        Label(f"  {f.name} [dim]- {f.mtime_ago}[/]"),
                        name=str(f.path),
                    )
                    for f in self._files
                ],
                id="newly-added-list",
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = event.item.name
        if name:
            self.post_message(FileChosen(Path(name)))

    def set_files(self, files: list[VideoFileInfo]) -> None:
        self._files = files
        self._file_count = len(files)

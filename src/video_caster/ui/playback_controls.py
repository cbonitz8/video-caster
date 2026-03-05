"""Playback controls widget: progress bar, buttons, volume, status."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, ProgressBar, Static

from video_caster.casting.base import PlaybackStatus


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class PlaybackControls(Widget):
    """Playback controls with progress bar and transport buttons."""

    status: reactive[PlaybackStatus] = reactive(PlaybackStatus)

    def compose(self) -> ComposeResult:
        yield Label("Nothing playing", id="now-playing")
        yield ProgressBar(total=100, show_percentage=False, id="progress-bar")
        yield Label("0:00 / 0:00", id="time-display")
        yield Static(id="transport-buttons")
        yield Label("Vol: 100%", id="volume-display")

    def watch_status(self, status: PlaybackStatus) -> None:
        try:
            now_playing = self.query_one("#now-playing", Label)
            progress = self.query_one("#progress-bar", ProgressBar)
            time_display = self.query_one("#time-display", Label)
            volume_display = self.query_one("#volume-display", Label)

            if status.state == "idle":
                now_playing.update("Nothing playing")
            else:
                state_icon = {
                    "playing": ">>",
                    "paused": "||",
                    "buffering": "...",
                    "stopped": "[]",
                }.get(status.state, "??")
                title = status.title or "Unknown"
                now_playing.update(f"{state_icon} {title}")

            progress.update(progress=status.progress * 100)
            time_display.update(
                f"{_format_time(status.current_time)} / {_format_time(status.duration)}"
            )
            volume_display.update(f"Vol: {int(status.volume * 100)}%")
        except Exception:
            pass

    def update_status(self, status: PlaybackStatus) -> None:
        self.status = status

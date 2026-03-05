"""Settings screen for managing watch folders."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static


class SettingsChanged(Message):
    """Posted when settings are saved."""
    pass


class SettingsScreen(ModalScreen[None]):
    """Modal screen for editing watch folders and settings."""

    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }
    #settings-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #settings-title {
        text-style: bold;
        text-align: center;
        padding: 0 0 1 0;
        color: $accent;
    }
    #folder-list {
        height: auto;
        max-height: 12;
        margin: 0 0 1 0;
    }
    .folder-row {
        height: 3;
    }
    #add-folder-row {
        height: 3;
        margin: 0 0 1 0;
    }
    #add-folder-input {
        width: 1fr;
    }
    #add-folder-btn {
        width: auto;
        min-width: 8;
    }
    #settings-buttons {
        height: 3;
        align: center middle;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(self, watch_folders: list[Path], **kwargs) -> None:
        super().__init__(**kwargs)
        self._folders = list(watch_folders)

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            yield Label("Settings", id="settings-title")
            yield Label("Watch Folders:")
            yield ListView(
                *self._make_items(),
                id="folder-list",
            )
            with Horizontal(id="add-folder-row"):
                yield Input(
                    placeholder="Add folder path (e.g. ~/Videos)",
                    id="add-folder-input",
                )
                yield Button("Add", id="add-folder-btn", variant="primary")
            with Horizontal(id="settings-buttons"):
                yield Button("Save", id="save-btn", variant="success")
                yield Button("Cancel", id="cancel-btn", variant="default")

    def _make_items(self) -> list[ListItem]:
        items = []
        for folder in self._folders:
            items.append(ListItem(
                Label(f"  {folder}  [dim](click to remove)[/]"),
                name=str(folder),
            ))
        return items

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = event.item.name
        if name:
            path = Path(name)
            if path in self._folders:
                self._folders.remove(path)
                self._refresh_list()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-folder-btn":
            self._add_folder()
        elif event.button.id == "save-btn":
            self._save()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "add-folder-input":
            self._add_folder()

    def _add_folder(self) -> None:
        inp = self.query_one("#add-folder-input", Input)
        raw = inp.value.strip()
        if not raw:
            return
        path = Path(raw).expanduser().resolve()
        if path not in self._folders:
            self._folders.append(path)
            self._refresh_list()
        inp.value = ""

    def _refresh_list(self) -> None:
        lv = self.query_one("#folder-list", ListView)
        lv.clear()
        for item in self._make_items():
            lv.append(item)

    def _save(self) -> None:
        from video_caster.config import load_config, save_config
        config = load_config()
        config.watch_folders = list(self._folders)
        save_config(config)
        self.post_message(SettingsChanged())
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @property
    def folders(self) -> list[Path]:
        return list(self._folders)

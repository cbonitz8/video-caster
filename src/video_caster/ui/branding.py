"""ASCII art branding header."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

# Using regular strings with explicit \\ for backslashes.
# Each line is padded to equal width for consistent rendering.
_LOGO_LINES = [
    " _   _  ___  ____  ____   ___      ___   __   ___  ___  ____  ____  ",
    "| | | ||_ _||  _ \\| ___| / _ \\    / __| /  \\ / __||_  || ___||  _ \\ ",
    "| |_| | | | | | | | |__ | | | |  | |   | /\\ |\\__ \\ | || |__ | |_) |",
    " \\   /  | | | |_| | |__ | |_| |  | |__ | -- ||__) || || |__ |  _ < ",
    "  \\_/  |___||____/|____| \\___/    \\____||_/\\_||___/ |_||____||_| \\_\\",
]


class BrandingHeader(Static):
    """Persistent ASCII art logo at the top of the left panel."""

    DEFAULT_CSS = """
    BrandingHeader {
        height: auto;
        padding: 1 2 0 2;
        text-align: center;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def on_mount(self) -> None:
        max_len = max(len(line) for line in _LOGO_LINES)
        padded = "\n".join(line.ljust(max_len) for line in _LOGO_LINES)
        text = Text(padded, style=Style(color="cyan", bold=True))
        self.update(text)

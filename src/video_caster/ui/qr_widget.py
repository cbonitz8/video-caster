"""QR code widget for the TUI — renders QR codes using Unicode half-block characters."""

from __future__ import annotations

import io
import logging

from textual.widgets import Static

log = logging.getLogger(__name__)


def _qr_to_text(url: str) -> str:
    """Generate a QR code as Unicode text using half-block characters.

    Uses upper/lower half-block chars so each text row encodes two QR rows:
      - Top black + bottom black  -> \u2588 (full block)
      - Top black + bottom white  -> \u2580 (upper half block)
      - Top white + bottom black  -> \u2584 (lower half block)
      - Top white + bottom white  -> ' ' (space)
    """
    try:
        import segno
    except ImportError:
        return f"[segno not installed]\n{url}"

    qr = segno.make(url, error="L")
    matrix = qr.matrix  # type: ignore[attr-defined]
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0

    lines: list[str] = []
    for y in range(0, rows, 2):
        line = []
        for x in range(cols):
            top = bool(matrix[y][x])
            bottom = bool(matrix[y + 1][x]) if y + 1 < rows else False
            if top and bottom:
                line.append("\u2588")
            elif top:
                line.append("\u2580")
            elif bottom:
                line.append("\u2584")
            else:
                line.append(" ")
        lines.append("".join(line))

    return "\n".join(lines)


class QRCodeWidget(Static):
    """Displays a QR code in the terminal."""

    DEFAULT_CSS = """
    QRCodeWidget {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._url: str = ""

    def set_url(self, url: str) -> None:
        self._url = url
        qr_text = _qr_to_text(url)
        self.update(f"{qr_text}\n{url}")

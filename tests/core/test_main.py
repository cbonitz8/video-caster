from __future__ import annotations

import socket

from video_caster.config import Config
from video_caster.core.__main__ import missing_tools, serve


def test_missing_tools_reports_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert missing_tools() == ["ffmpeg", "ffprobe"]


async def test_serve_exits_1_when_port_taken(tmp_path, watch_dir):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    port = blocker.getsockname()[1]
    try:
        config = Config(watch_folders=[watch_dir], history_db_path=tmp_path / "h.db")
        code = await serve(port, config=config, token_path=tmp_path / "core-token")
    finally:
        blocker.close()
    assert code == 1

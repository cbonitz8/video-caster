from __future__ import annotations

import socket
import sys

import pytest

from video_caster.config import Config
from video_caster.core.__main__ import main, missing_tools, serve


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
    assert not (tmp_path / "core-token").exists()


def test_main_logs_path_when_ffmpeg_missing(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["video-caster-core"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "ffmpeg, ffprobe" in caplog.text
    assert str(tmp_path) in caplog.text

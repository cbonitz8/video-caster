from __future__ import annotations

import pytest

from video_caster.core import auth, paths
from video_caster.core.errors import Forbidden, Unauthorized
from tests.conftest import make_video


def test_is_under_accepts_nested(watch_dir):
    assert paths.is_under(watch_dir / "Show" / "a.mkv", [watch_dir])


def test_is_under_rejects_dotdot(watch_dir):
    assert not paths.is_under(watch_dir / ".." / "secret.mkv", [watch_dir])


def test_is_under_rejects_symlink_leading_out(watch_dir, tmp_path):
    outside = tmp_path / "outside"
    make_video(outside / "x.mkv")
    (watch_dir / "link").symlink_to(outside)
    assert not paths.is_under(watch_dir / "link" / "x.mkv", [watch_dir])


def test_is_under_rejects_name_prefix_sibling(tmp_path):
    movies = tmp_path / "Movies"
    movies.mkdir()
    assert not paths.is_under(tmp_path / "Movies2" / "a.mkv", [movies])


def test_list_folder_dirs_first_videos_only(watch_dir):
    (watch_dir / "B Season").mkdir()
    (watch_dir / "notes.txt").write_text("x")
    make_video(watch_dir / ".hidden.mkv")
    assert paths.list_folder(watch_dir) == [
        {"path": str(watch_dir / "B Season"), "name": "B Season", "is_dir": True},
        {"path": str(watch_dir / "Movie.mkv"), "name": "Movie.mkv", "is_dir": False, "size": 1,
         "title": "Movie", "subtitle": None},
    ]


def test_watch_roots_skips_missing(watch_dir, tmp_path):
    assert paths.watch_roots([watch_dir, tmp_path / "unplugged"]) == [
        {"path": str(watch_dir), "name": "watch", "is_dir": True},
    ]


def test_write_token_is_private_and_rotates(tmp_path):
    token_path = tmp_path / "sub" / "core-token"
    first = auth.write_token(token_path)
    second = auth.write_token(token_path)
    assert first != second
    assert len(second) >= 40
    assert token_path.read_text() == second
    assert token_path.stat().st_mode & 0o777 == 0o600


def test_is_local():
    assert auth.is_local(None, "abc") is False
    assert auth.is_local("Bearer abc", "abc") is True
    for bad in ("Bearer nope", "abc", "Bearer ünïcode"):
        with pytest.raises(Forbidden):
            auth.is_local(bad, "abc")


def test_require_local():
    with pytest.raises(Unauthorized):
        auth.require_local(None, "abc")
    with pytest.raises(Forbidden):
        auth.require_local("Bearer nope", "abc")
    auth.require_local("Bearer abc", "abc")


def test_list_folder_skips_dangling_symlink(watch_dir, tmp_path):
    (watch_dir / "gone.mkv").symlink_to(tmp_path / "unplugged" / "gone.mkv")
    assert [e["name"] for e in paths.list_folder(watch_dir)] == ["Movie.mkv"]

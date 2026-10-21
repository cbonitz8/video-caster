from __future__ import annotations

import pytest

from video_caster import posters


@pytest.mark.parametrize("title,expected", [
    ("Ted Lasso", "ted-lasso"),
    ("Avatar: The Legend of Aang", "avatar-the-legend-of-aang"),
    ("The Matrix (1999)", "the-matrix-1999"),
    ("  --Greyhounds' Day Off--  ", "greyhounds-day-off"),
    ("!!!", ""),
])
def test_slug(title, expected):
    assert posters.slug(title) == expected


def test_art_index_and_lookup(tmp_path):
    for name in ("ted-lasso.png", "ted-lasso.jpg", "ted-lasso-wide.webp", ".ted-lasso.jpg", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    art = posters.art_for(posters.art_index(tmp_path), "Ted Lasso")
    assert art["slug"] == "ted-lasso"
    assert art["poster"].startswith("/posters/ted-lasso.jpg?v=")
    assert art["wide"].startswith("/posters/ted-lasso-wide.webp?v=")


def test_missing_art_and_missing_folder(tmp_path):
    assert posters.art_index(tmp_path / "nope") == {}
    assert posters.art_for({}, "Show") == {"slug": "show", "poster": None, "wide": None}


def test_empty_slug_never_matches(tmp_path):
    (tmp_path / ".jpg").write_bytes(b"x")
    (tmp_path / "-wide.jpg").write_bytes(b"x")
    art = posters.art_for(posters.art_index(tmp_path), "!!!")
    assert art["poster"] is None and art["wide"] is None


@pytest.mark.parametrize("name,ok", [
    ("show.jpg", True), ("show.WEBP", True), ("show.txt", False), (".hidden.jpg", False),
    ("../show.jpg", False), ("a\\b.jpg", False), ("a\0.jpg", False),
])
def test_is_art_name(name, ok):
    assert posters.is_art_name(name) is ok

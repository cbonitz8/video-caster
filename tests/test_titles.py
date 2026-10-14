from __future__ import annotations

from pathlib import Path

import pytest

from video_caster.titles import display_title


@pytest.mark.parametrize("path, title, subtitle", [
    ("/tv/Ted.Lasso.S04E05.Riches.of.Embarrassment.1080p.WEB-DL.mkv",
     "Ted Lasso", "S04E05 · Riches of Embarrassment"),
    ("/tv/Ted Lasso - S04E07 - Yes & Baby.mkv", "Ted Lasso", "S04E07 · Yes & Baby"),
    ("/tv/Show.Name.1x03.Pilot.mkv", "Show Name", "S01E03 · Pilot"),
    ("/tv/Show/Season 1/03 - Pilot.mkv", "Show", "S01E03 · Pilot"),
    ("/tv/Show/Season 2/Episode 04.mkv", "Show", "S02E04"),
    ("/tv/Show/Season 1/S01E03.mkv", "Show", "S01E03"),
    ("/tv/Ted.Lasso.S04E05.1080p.mkv", "Ted Lasso", "S04E05"),
    ("/tv/Show.S01E02.Second.H.264.DDP5.1.mkv", "Show", "S01E02 · Second"),
    ("/m/The.Matrix.1999.1080p.BluRay.x264.mkv", "The Matrix (1999)", None),
    ("/m/Blade.Runner.2049.2017.2160p.mkv", "Blade Runner 2049 (2017)", None),
    ("/m/2001.A.Space.Odyssey.1968.mkv", "2001 A Space Odyssey (1968)", None),
    ("/m/Heat (1995).mp4", "Heat (1995)", None),
    ("/m/some_random_clip.2024-03.mp4", "some random clip 2024-03", None),
    ("/m/Some.Movie.1920x1080.mkv", "Some Movie 1920x1080", None),
    ("/m/Isaac.Clip.mkv", "Isaac Clip", None),
])
def test_display_title(path, title, subtitle):
    assert display_title(Path(path)) == {"title": title, "subtitle": subtitle}


def test_only_quality_tokens_falls_back_to_cleaned_stem():
    assert display_title(Path("/m/1080p.x264.mkv")) == {"title": "1080p x264", "subtitle": None}


def test_title_never_empty():
    assert display_title(Path("/m/___.mkv")) == {"title": "___", "subtitle": None}

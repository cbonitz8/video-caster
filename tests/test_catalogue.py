from __future__ import annotations

from pathlib import Path

from video_caster.catalogue import WATCHED_AT, Catalogue, EpisodeKey, WatchStates, episode_key
from video_caster.storage.history import WatchRecord

TV = Path("/Volumes/stanley/Videos/entertainment")


def record(path: Path, *, position=0.0, duration=100.0, completed=False, at=1.0, id=1) -> WatchRecord:
    return WatchRecord(
        id=id, file_path=str(path), file_name=path.name, device_id="dev", device_name="Living Room",
        started_at=at, last_updated_at=at, duration=duration, position=position, completed=completed,
    )


def show(*codes, folder=Path("/tv/Show"), name="Show") -> list[Path]:
    return [folder / f"{name}.{code}.mkv" for code in codes]


def test_episode_key_survives_a_rename_into_season_folders():
    old = TV / "ted lasso s4" / "Ted.Lasso.S04E05.Riches.of.Embarrassment.1080p.HEVC.x265-MeGusta[EZTVx.to].mkv"
    new = TV / "Ted Lasso" / "Season 4" / "Ted Lasso - S04E05 - Riches of Embarrassment.mkv"
    assert episode_key(old) == episode_key(new) == EpisodeKey("ted lasso", 4, 5)


def test_movies_have_no_episode_key():
    assert episode_key(Path("/m/Knights Tale.mkv")) is None


def test_old_completed_row_marks_the_renamed_copy_watched():
    old = TV / "ted lasso s4" / "Ted.Lasso.S04E05.Riches.of.Embarrassment.1080p.HEVC.x265-MeGusta[EZTVx.to].mkv"
    new = TV / "Ted Lasso" / "Season 4" / "Ted Lasso - S04E05 - Riches of Embarrassment.mkv"
    states = WatchStates([record(old, position=95.0, completed=True)])
    assert states.is_watched(new)


def test_newest_row_across_copies_decides():
    old = TV / "avatar seven havens" / "Avatar Seven Havens - S01E01 - On the Horizon.mkv"
    new = TV / "Avatar Seven Havens" / "Season 1" / "Avatar Seven Havens - S01E01 - On the Horizon.mkv"
    states = WatchStates([
        record(old, position=95.0, completed=True, at=1.0, id=1),
        record(new, position=40.0, at=2.0, id=2),
    ])
    assert not states.is_watched(old)
    assert states.resume_position(old) == states.resume_position(new) == 40.0


def test_movies_stay_per_file():
    a, b = Path("/m/a/Movie.mkv"), Path("/m/b/Movie.mkv")
    states = WatchStates([record(a, position=95.0, completed=True)])
    assert states.is_watched(a)
    assert states.of(b) is None


def test_watched_at_the_threshold():
    clip = Path("/m/Clip.mkv")
    assert WatchStates([record(clip, position=WATCHED_AT * 100.0)]).is_watched(clip)
    assert not WatchStates([record(clip, position=WATCHED_AT * 100.0 - 1)]).is_watched(clip)


def test_unknown_duration_is_never_watched():
    clip = Path("/m/Clip.mkv")
    states = WatchStates([record(clip, position=50.0, duration=0.0)])
    assert not states.is_watched(clip)
    assert states.resume_position(clip) == 50.0


def test_no_resume_for_watched_or_untouched():
    clip, other = Path("/m/Clip.mkv"), Path("/m/Other.mkv")
    states = WatchStates([record(clip, position=95.0, completed=True)])
    assert states.resume_position(clip) is None
    assert states.resume_position(other) is None


def test_show_of_groups_case_insensitively():
    catalogue = Catalogue([Path("/tv/A/Show.S01E02.mkv"), Path("/tv/B/show.S01E01.mkv"), Path("/m/Movie.mkv")])
    assert catalogue.show_of(Path("/tv/A/Show.S01E02.mkv")) == "show"
    assert catalogue.show_of(Path("/m/Movie.mkv")) is None
    assert list(catalogue.shows) == ["show"]
    assert catalogue.movies == [Path("/m/Movie.mkv")]


def test_next_after_goes_forward():
    e1, e2, e3 = show("S01E01", "S01E02", "S01E03")
    assert Catalogue([e3, e1, e2]).next_after(e1) == e2


def test_next_after_crosses_a_gap():
    e4, e6 = show("S04E04", "S04E06")
    assert Catalogue([e4, e6]).next_after(e4) == e6


def test_next_after_crosses_folders():
    e1 = Path("/tv/A/Show.S01E01.mkv")
    e2 = Path("/tv/B/show.S01E02.mkv")
    assert Catalogue([e1, e2]).next_after(e1) == e2


def test_next_after_crosses_a_missing_season():
    s1, s3 = show("S01E09", "S03E01")
    assert Catalogue([s1, s3]).next_after(s1) == s3


def test_nothing_after_the_last_episode():
    e1, e2 = show("S02E01", "S02E02")
    assert Catalogue([e1, e2]).next_after(e2) is None


def test_next_after_skips_other_copies_of_the_same_episode():
    e1 = Path("/tv/A/Show.S01E01.mkv")
    copy = Path("/tv/B/Show.S01E01.mkv")
    e2 = Path("/tv/A/Show.S01E02.mkv")
    assert Catalogue([e1, copy, e2]).next_after(e1) == e2


def test_next_after_a_file_outside_the_catalogue_matches_by_episode():
    outside = Path("/Users/me/Movies/Ted.Lasso.S04E04.1080p.HEVC.x265-MeGusta[EZTVx.to].mkv")
    e5 = TV / "Ted Lasso" / "Season 4" / "Ted Lasso - S04E05 - Riches of Embarrassment.mkv"
    assert Catalogue([e5]).next_after(outside) == e5


def test_no_next_for_unknown_shows_or_movies():
    catalogue = Catalogue(show("S01E01", "S01E02"))
    assert catalogue.next_after(Path("/x/Other.S01E01.mkv")) is None
    assert catalogue.next_after(Path("/m/Movie.mkv")) is None


def test_next_pick_resumes_the_library_copy_of_an_in_progress_episode():
    gone = Path("/old/Show.S01E02.mkv")
    e1, e2 = show("S01E01", "S01E02")
    catalogue = Catalogue([e1, e2])
    states = WatchStates([record(gone, position=30.0, at=5.0)])
    assert catalogue.next_pick("show", states) == (e2, 5.0)


def test_next_pick_moves_past_watched():
    e1, e2, e3 = show("S01E01", "S01E02", "S01E03")
    states = WatchStates([
        record(e2, position=95.0, completed=True, at=1.0, id=1),
        record(e1, position=95.0, completed=True, at=2.0, id=2),
    ])
    assert Catalogue([e1, e2, e3]).next_pick("show", states) == (e3, 2.0)


def test_up_next_and_next_agree_while_watching_forward():
    eps = show("S01E01", "S01E02", "S02E01", "S02E03")
    catalogue = Catalogue(eps)
    rows = []
    for i, ep in enumerate(eps[:-1]):
        rows.append(record(ep, position=95.0, completed=True, at=float(i), id=i))
        pick, _ = catalogue.next_pick("show", WatchStates(rows))
        assert pick == catalogue.next_after(ep) == eps[i + 1]


def test_rewatch_next_differs_from_up_next_on_purpose():
    e1, e2, e3 = show("S01E01", "S01E02", "S01E03")
    catalogue = Catalogue([e1, e2, e3])
    states = WatchStates([
        record(e1, position=95.0, completed=True, at=1.0, id=1),
        record(e2, position=95.0, completed=True, at=2.0, id=2),
        record(e3, position=95.0, completed=True, at=3.0, id=3),
        record(e1, position=95.0, completed=True, at=4.0, id=4),
    ])
    assert catalogue.next_after(e1) == e2
    assert catalogue.next_pick("show", states) == (None, 4.0)

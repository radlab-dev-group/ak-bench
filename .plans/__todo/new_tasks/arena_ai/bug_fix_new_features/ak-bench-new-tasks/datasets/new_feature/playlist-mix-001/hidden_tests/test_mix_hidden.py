"""The specification, tested rule by rule.

Every assertion here is a sentence from the docstring of ``build_mix``.
"""

from __future__ import annotations

import pytest

from playlist import Track, build_mix, total_duration


def track(track_id: str, artist: str, duration: int, title: str = "Song"):
    return Track(track_id, title, artist, duration)


def test_the_mix_never_exceeds_the_target():
    tracks = [track("A", "Alpha", 400), track("B", "Beta", 300), track("C", "Gamma", 100)]
    mix = build_mix(tracks, 500)
    assert total_duration(mix) <= 500
    assert [t.track_id for t in mix] == ["A", "C"]


def test_longest_first_wins_over_input_order():
    tracks = [track("C", "Gamma", 100), track("B", "Beta", 300), track("A", "Alpha", 400)]
    mix = build_mix(tracks, 500)
    assert [t.track_id for t in mix] == ["A", "C"]


def test_equal_durations_break_on_track_id():
    tracks = [track("B", "Beta", 200), track("A", "Alpha", 200)]
    mix = build_mix(tracks, 200)
    assert [t.track_id for t in mix] == ["A"]


def test_the_result_is_sorted_by_artist_then_title():
    tracks = [
        track("T1", "Beta", 100, title="Zulu"),
        track("T2", "Alpha", 100, title="Yankee"),
        track("T3", "Alpha", 100, title="Xray"),
    ]
    # T2 and T3 share an artist, so only one of them can be selected; the
    # longer-first walk ties on duration and track_id, so T2 is picked.
    mix = build_mix(tracks, 200)
    assert [(t.artist, t.title) for t in mix] == [("Alpha", "Yankee"), ("Beta", "Zulu")]


def test_tolerance_is_inclusive_at_the_boundary():
    tracks = [track("A", "Alpha", 300)]
    assert [t.track_id for t in build_mix(tracks, 500, tolerance=200)] == ["A"]
    assert build_mix(tracks, 500, tolerance=199) == []


def test_a_single_track_longer_than_the_target_selects_nothing():
    assert build_mix([track("A", "Alpha", 600)], 500) == []
    mix = build_mix([track("A", "Alpha", 600)], 500, tolerance=100)
    assert mix == []


def test_artist_comparison_is_exact():
    tracks = [track("A", "Alpha", 300), track("a", "alpha", 200)]
    mix = build_mix(tracks, 500)
    assert [t.track_id for t in mix] == ["A", "a"]


def test_an_empty_track_list_returns_an_empty_mix():
    assert build_mix([], 500) == []


def test_invalid_arguments_are_refused():
    tracks = [track("A", "Alpha", 300)]
    with pytest.raises(ValueError):
        build_mix(tracks, 0)
    with pytest.raises(ValueError):
        build_mix(tracks, -100)
    with pytest.raises(ValueError):
        build_mix(tracks, 500, tolerance=-1)

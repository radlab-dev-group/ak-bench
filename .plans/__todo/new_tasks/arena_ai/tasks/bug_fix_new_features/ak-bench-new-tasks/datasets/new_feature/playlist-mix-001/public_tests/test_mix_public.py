"""The examples a developer is given: the shape of the contract, not its edges.

They fail on the base commit (the feature is missing) and pass once it is
implemented. They are a subset of the contract, not the whole of it.
"""

from __future__ import annotations

from playlist import Track, build_mix


def track(track_id: str, artist: str, duration: int, title: str = "Song"):
    return Track(track_id, title, artist, duration)


def test_a_mix_can_fill_the_target_exactly():
    tracks = [track("A", "Alpha", 300), track("B", "Beta", 200), track("C", "Gamma", 200)]
    mix = build_mix(tracks, 500)
    assert [t.track_id for t in mix] == ["A", "B"]


def test_a_shortfall_beyond_tolerance_returns_nothing():
    tracks = [track("A", "Alpha", 300), track("B", "Beta", 200), track("C", "Gamma", 200)]
    assert build_mix(tracks, 490) == []
    mix = build_mix(tracks, 490, tolerance=200)
    assert [t.track_id for t in mix] == ["A"]


def test_at_most_one_track_per_artist():
    tracks = [track("A1", "Alpha", 300), track("A2", "Alpha", 200), track("B", "Beta", 200)]
    mix = build_mix(tracks, 500)
    assert [t.track_id for t in mix] == ["A1", "B"]

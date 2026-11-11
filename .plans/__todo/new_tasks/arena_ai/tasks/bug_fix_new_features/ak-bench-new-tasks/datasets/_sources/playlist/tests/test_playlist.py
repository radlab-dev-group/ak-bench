"""The finished part of the fixture: the track record and single-disc order.

The suite deliberately only uses single-disc albums, so a defect in how
discs and track numbers combine is invisible here.
"""

from __future__ import annotations

import pytest

from playlist import Track, album_order, build_queue, total_duration


def test_a_track_needs_an_id_and_positive_numbers():
    with pytest.raises(ValueError):
        Track("", "Song", "Artist", 180)
    with pytest.raises(ValueError):
        Track("T1", "Song", "Artist", 0)
    with pytest.raises(ValueError):
        Track("T1", "Song", "Artist", 180, disc=0)
    with pytest.raises(ValueError):
        Track("T1", "Song", "Artist", 180, track_no=0)


def test_single_disc_tracks_play_in_track_order():
    tracks = [
        Track("T3", "Third", "Artist", 180, track_no=3),
        Track("T1", "First", "Artist", 180, track_no=1),
        Track("T2", "Second", "Artist", 180, track_no=2),
    ]
    assert [track.track_id for track in album_order(tracks)] == ["T1", "T2", "T3"]


def test_the_total_duration_is_the_sum():
    tracks = [Track("T1", "A", "Artist", 180), Track("T2", "B", "Artist", 240)]
    assert total_duration(tracks) == 420
    assert total_duration([]) == 0


def test_a_queue_skips_without_reordering():
    tracks = [
        Track("T1", "First", "Artist", 180, track_no=1),
        Track("T2", "Second", "Artist", 180, track_no=2),
        Track("T3", "Third", "Artist", 180, track_no=3),
    ]
    queue = build_queue(tracks, skip_ids={"T2"})
    assert [track.track_id for track in queue] == ["T1", "T3"]

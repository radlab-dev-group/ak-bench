"""What a developer is told about this defect: disc comes before track.

These tests are visible to the agent. They state the rule and probe it at
the edges the hidden tests also care about, so an agent can find the defect
without being handed the exact assertions the evaluation uses.
"""

from __future__ import annotations

from playlist import Track, album_order, build_queue


def test_disc_one_plays_in_full_before_disc_two_starts():
    tracks = [
        Track("D2T1", "Opener", "Artist", 180, disc=2, track_no=1),
        Track("D1T2", "Second", "Artist", 180, disc=1, track_no=2),
        Track("D1T1", "First", "Artist", 180, disc=1, track_no=1),
    ]
    assert [track.track_id for track in album_order(tracks)] == ["D1T1", "D1T2", "D2T1"]


def test_a_queue_keeps_the_album_order_while_skipping():
    tracks = [
        Track("D2T1", "Opener", "Artist", 180, disc=2, track_no=1),
        Track("D1T1", "First", "Artist", 180, disc=1, track_no=1),
        Track("D1T2", "Second", "Artist", 180, disc=1, track_no=2),
    ]
    queue = build_queue(tracks, skip_ids={"D1T1"})
    assert [track.track_id for track in queue] == ["D1T2", "D2T1"]

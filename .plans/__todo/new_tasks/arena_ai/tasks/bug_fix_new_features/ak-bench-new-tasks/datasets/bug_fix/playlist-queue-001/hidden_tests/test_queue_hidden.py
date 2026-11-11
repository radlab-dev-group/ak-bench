"""The defect, proven from every side the mutation can hide behind.

The hidden tests pass on the base commit and fail once the mutation is
applied; that is the contract of a bug-fix task (docs/DATASETS.md). They
cover restarting track numbers, three discs, the track-id tie-break, and
the queue built on top of the order.
"""

from __future__ import annotations

from playlist import Track, album_order, build_queue, total_duration


def track(track_id: str, disc: int, track_no: int, duration: int = 180):
    return Track(track_id, f"Title {track_id}", "Artist", duration, disc=disc, track_no=track_no)


def test_disc_comes_before_track_number():
    tracks = [track("D2T1", 2, 1), track("D1T2", 1, 2), track("D1T1", 1, 1)]
    assert [t.track_id for t in album_order(tracks)] == ["D1T1", "D1T2", "D2T1"]


def test_three_discs_play_in_disc_order():
    tracks = [
        track("D3T1", 3, 1),
        track("D2T2", 2, 2),
        track("D1T3", 1, 3),
        track("D2T1", 2, 1),
        track("D1T1", 1, 1),
        track("D3T2", 3, 2),
        track("D1T2", 1, 2),
    ]
    assert [t.track_id for t in album_order(tracks)] == [
        "D1T1", "D1T2", "D1T3", "D2T1", "D2T2", "D3T1", "D3T2",
    ]


def test_equal_disc_and_track_number_break_on_track_id():
    tracks = [track("B", 1, 1), track("A", 1, 1)]
    assert [t.track_id for t in album_order(tracks)] == ["A", "B"]


def test_a_single_disc_still_plays_in_track_order():
    tracks = [track("T3", 1, 3), track("T1", 1, 1), track("T2", 1, 2)]
    assert [t.track_id for t in album_order(tracks)] == ["T1", "T2", "T3"]


def test_a_queue_skips_without_reordering_across_discs():
    tracks = [track("D2T1", 2, 1), track("D1T2", 1, 2), track("D1T1", 1, 1)]
    queue = build_queue(tracks, skip_ids={"D1T2"})
    assert [t.track_id for t in queue] == ["D1T1", "D2T1"]


def test_the_total_duration_is_unaffected_by_order():
    tracks = [track("D2T1", 2, 1, 200), track("D1T1", 1, 1, 100)]
    assert total_duration(tracks) == 300
    assert total_duration(album_order(tracks)) == 300


def test_an_empty_album_has_an_empty_order_and_queue():
    assert album_order([]) == []
    assert build_queue([]) == []

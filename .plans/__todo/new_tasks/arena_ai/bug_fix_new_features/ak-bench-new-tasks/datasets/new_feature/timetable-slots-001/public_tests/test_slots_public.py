"""The examples a developer is given: the shape of the contract, not its edges.

They fail on the base commit (the feature is missing) and pass once it is
implemented. They are a subset of the contract, not the whole of it.
"""

from __future__ import annotations

from timetable import find_slot


def test_an_empty_timetable_starts_at_the_window_start():
    assert find_slot([], 60, 540, 720) == 540


def test_a_slot_after_a_busy_interval():
    assert find_slot([(540, 600)], 60, 540, 720) == 600


def test_a_slot_before_a_busy_interval():
    assert find_slot([(600, 660)], 60, 540, 720) == 540


def test_a_gap_pushes_the_slot_later():
    assert find_slot([(540, 600)], 60, 540, 720, gap=15) == 615


def test_a_full_window_has_no_slot():
    assert find_slot([(540, 720)], 60, 540, 720) is None

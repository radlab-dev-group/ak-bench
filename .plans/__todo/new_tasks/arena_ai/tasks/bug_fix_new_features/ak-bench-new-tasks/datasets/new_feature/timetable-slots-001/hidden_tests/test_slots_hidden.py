"""The specification, tested rule by rule.

Every assertion here is a sentence from the docstring of ``find_slot``.
"""

from __future__ import annotations

import pytest

from timetable import find_slot


def test_busy_intervals_may_be_unsorted():
    busy = [(660, 720), (540, 600)]
    assert find_slot(busy, 60, 540, 720) == 600


def test_overlapping_busy_intervals_are_treated_as_one_block():
    busy = [(540, 620), (600, 680)]
    assert find_slot(busy, 40, 540, 720) == 680


def test_busy_intervals_outside_the_window_do_not_block():
    busy = [(0, 100), (900, 1000)]
    assert find_slot(busy, 60, 540, 720) == 540


def test_a_slot_may_end_exactly_at_the_window_end():
    assert find_slot([(540, 660)], 60, 540, 720) == 660


def test_a_slot_may_fill_the_whole_window():
    assert find_slot([], 180, 540, 720) == 540


def test_a_duration_longer_than_the_window_fits_nowhere():
    assert find_slot([], 181, 540, 720) is None
    assert find_slot([], 200, 540, 720) is None


def test_the_gap_applies_before_a_busy_interval_too():
    # 540 + 45 = 585, which is 15 minutes before the busy interval at 600.
    assert find_slot([(600, 660)], 45, 540, 720, gap=15) == 540
    # 540 + 46 = 586, which is only 14 minutes before it: no fit before.
    assert find_slot([(600, 660)], 46, 540, 780, gap=15) == 675


def test_the_gap_applies_after_a_busy_interval():
    assert find_slot([(540, 600)], 60, 540, 720, gap=30) == 630


def test_a_gap_can_push_the_only_slot_out_of_the_window():
    assert find_slot([(540, 600)], 60, 540, 660, gap=61) is None


def test_the_earliest_of_several_slots_wins():
    busy = [(540, 570), (630, 720)]
    assert find_slot(busy, 30, 540, 720) == 570


def test_a_slot_between_two_busy_intervals():
    busy = [(540, 600), (700, 760)]
    assert find_slot(busy, 60, 540, 780) == 600


def test_invalid_arguments_are_refused():
    with pytest.raises(ValueError):
        find_slot([], 0, 540, 720)
    with pytest.raises(ValueError):
        find_slot([], -30, 540, 720)
    with pytest.raises(ValueError):
        find_slot([], 60, 540, 720, gap=-1)
    with pytest.raises(ValueError):
        find_slot([], 60, 720, 540)
    with pytest.raises(ValueError):
        find_slot([], 60, 540, 540)

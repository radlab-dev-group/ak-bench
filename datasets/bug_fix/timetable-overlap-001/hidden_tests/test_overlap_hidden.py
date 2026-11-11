"""The defect, proven from every side the mutation can hide behind.

The hidden tests pass on the base commit and fail once the mutation is
applied; that is the contract of a bug-fix task (docs/DATASETS.md). They
cover touching intervals in both directions, a one-minute overlap, and the
two higher-level checks built on `overlaps`.
"""

from __future__ import annotations

from timetable import Lesson, conflicts, is_free, overlaps


def test_touching_intervals_do_not_overlap_in_either_direction():
    assert not overlaps(0, 60, 60, 120)
    assert not overlaps(60, 120, 0, 60)
    assert not overlaps(600, 660, 540, 600)


def test_a_one_minute_overlap_is_still_an_overlap():
    assert overlaps(540, 601, 600, 660)
    assert overlaps(599, 660, 540, 600)
    assert overlaps(540, 600, 599, 660)


def test_identical_and_contained_intervals_overlap():
    assert overlaps(540, 600, 540, 600)
    assert overlaps(540, 700, 580, 620)
    assert overlaps(580, 620, 540, 700)


def test_disjoint_intervals_with_a_gap_do_not_overlap():
    assert not overlaps(540, 600, 601, 660)
    assert not overlaps(601, 660, 540, 600)


def test_conflicts_excludes_back_to_back_pairs_but_keeps_real_ones():
    lessons = [
        Lesson("A", "Maths", 540, 600),
        Lesson("B", "History", 600, 660),
        Lesson("C", "Art", 659, 720),
    ]
    assert conflicts(lessons) == [("B", "C")]


def test_conflicts_is_independent_of_input_order():
    lessons = [
        Lesson("C", "Art", 659, 720),
        Lesson("B", "History", 600, 660),
        Lesson("A", "Maths", 540, 600),
    ]
    assert conflicts(lessons) == [("B", "C")]


def test_is_free_accepts_a_slot_ending_when_a_lesson_starts():
    lessons = [Lesson("A", "Maths", 600, 660)]
    assert is_free(lessons, 540, 600)


def test_is_free_rejects_a_slot_overlapping_by_one_minute():
    lessons = [Lesson("A", "Maths", 600, 660)]
    assert not is_free(lessons, 540, 601)
    assert not is_free(lessons, 659, 720)


def test_a_chain_of_back_to_back_lessons_has_no_conflicts():
    lessons = [
        Lesson("A", "Maths", 540, 600),
        Lesson("B", "History", 600, 660),
        Lesson("C", "Art", 660, 720),
    ]
    assert conflicts(lessons) == []
    assert is_free(lessons, 720, 780)

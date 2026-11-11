"""The finished part of the fixture: the lesson record and overlap checks.

The suite deliberately stays away from back-to-back intervals, so a defect
at that boundary is invisible here.
"""

from __future__ import annotations

import pytest

from timetable import Lesson, conflicts, is_free, overlaps


def test_a_lesson_knows_its_duration():
    assert Lesson("L1", "Maths", 540, 600).duration == 60


def test_a_lesson_needs_an_id_and_a_positive_span():
    with pytest.raises(ValueError):
        Lesson("", "Maths", 540, 600)
    with pytest.raises(ValueError):
        Lesson("L1", "Maths", 600, 600)
    with pytest.raises(ValueError):
        Lesson("L1", "Maths", 600, 540)
    with pytest.raises(ValueError):
        Lesson("L1", "Maths", -10, 60)


def test_disjoint_intervals_do_not_overlap():
    assert not overlaps(540, 600, 620, 680)
    assert not overlaps(620, 680, 540, 600)


def test_partly_overlapping_intervals_overlap():
    assert overlaps(540, 620, 600, 680)
    assert overlaps(600, 680, 540, 620)


def test_a_contained_interval_overlaps():
    assert overlaps(540, 700, 580, 620)
    assert overlaps(580, 620, 540, 700)


def test_conflicts_reports_the_overlapping_pair():
    lessons = [
        Lesson("B", "History", 600, 680),
        Lesson("A", "Maths", 540, 620),
        Lesson("C", "Art", 720, 780),
    ]
    assert conflicts(lessons) == [("A", "B")]


def test_conflicts_is_empty_when_nothing_overlaps():
    lessons = [Lesson("A", "Maths", 540, 600), Lesson("B", "Art", 720, 780)]
    assert conflicts(lessons) == []


def test_is_free_for_a_clear_slot_and_not_for_a_busy_one():
    lessons = [Lesson("A", "Maths", 540, 600)]
    assert is_free(lessons, 620, 680)
    assert not is_free(lessons, 560, 620)


def test_is_free_refuses_an_empty_slot():
    with pytest.raises(ValueError):
        is_free([], 600, 600)

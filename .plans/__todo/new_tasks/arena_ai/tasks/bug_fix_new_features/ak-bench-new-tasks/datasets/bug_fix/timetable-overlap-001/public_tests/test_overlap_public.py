"""What a developer is told about this defect: intervals are half-open.

These tests are visible to the agent. They state the rule and probe it at
the edges the hidden tests also care about, so an agent can find the defect
without being handed the exact assertions the evaluation uses.
"""

from __future__ import annotations

from timetable import Lesson, conflicts, is_free, overlaps


def test_back_to_back_intervals_do_not_overlap():
    assert not overlaps(540, 600, 600, 660)
    assert not overlaps(600, 660, 540, 600)


def test_intervals_sharing_one_minute_do_overlap():
    assert overlaps(540, 601, 600, 660)
    assert overlaps(600, 660, 540, 601)


def test_back_to_back_lessons_do_not_conflict():
    lessons = [
        Lesson("A", "Maths", 540, 600),
        Lesson("B", "History", 600, 660),
    ]
    assert conflicts(lessons) == []


def test_a_slot_starting_when_a_lesson_ends_is_free():
    lessons = [Lesson("A", "Maths", 540, 600)]
    assert is_free(lessons, 600, 660)

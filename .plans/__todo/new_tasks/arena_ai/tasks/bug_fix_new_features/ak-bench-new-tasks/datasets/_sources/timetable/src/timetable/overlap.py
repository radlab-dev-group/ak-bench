"""Whether lessons overlap. Intervals are half-open: ``[start, end)``.

Two intervals overlap when each starts before the other ends. An interval
that ends exactly when the other starts does not overlap it, so
back-to-back lessons are free to follow each other.
"""

from __future__ import annotations

from collections.abc import Iterable

from timetable.model import Lesson


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """True when ``[a_start, a_end)`` and ``[b_start, b_end)`` share a minute."""
    return a_start < b_end and b_start < a_end


def conflicts(lessons: Iterable[Lesson]) -> list[tuple[str, str]]:
    """Every pair of lesson ids that overlap, in a deterministic order.

    Each pair is ``(smaller_id, larger_id)`` and the list is sorted, so the
    result depends only on the lessons, never on the order they were given.
    """
    lessons = list(lessons)
    pairs: list[tuple[str, str]] = []
    for index, first in enumerate(lessons):
        for second in lessons[index + 1 :]:
            if overlaps(first.start, first.end, second.start, second.end):
                pairs.append(tuple(sorted((first.lesson_id, second.lesson_id))))
    return sorted(pairs)


def is_free(lessons: Iterable[Lesson], start: int, end: int) -> bool:
    """True when no lesson overlaps ``[start, end)``."""
    if end <= start:
        raise ValueError(f"end must be after start, got [{start}, {end})")
    return not any(
        overlaps(start, end, lesson.start, lesson.end) for lesson in lessons
    )

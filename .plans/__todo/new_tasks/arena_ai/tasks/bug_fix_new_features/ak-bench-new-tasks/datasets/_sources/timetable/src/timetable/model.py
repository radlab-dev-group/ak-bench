"""The lesson record. Times are minutes from midnight."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lesson:
    """One lesson: a half-open interval ``[start, end)`` in minutes.

    A lesson that ends at minute 600 and another that starts at minute 600
    are back-to-back, not overlapping: the first occupies minutes up to but
    not including 600, and the second starts at 600.
    """

    lesson_id: str
    title: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not self.lesson_id:
            raise ValueError("a lesson needs an id")
        if self.start < 0:
            raise ValueError(f"start cannot be negative, got {self.start}")
        if self.end <= self.start:
            raise ValueError(
                f"end must be after start, got [{self.start}, {self.end})"
            )

    @property
    def duration(self) -> int:
        """How many minutes the lesson occupies."""
        return self.end - self.start

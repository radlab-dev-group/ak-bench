"""A lesson timetable: lessons as half-open intervals, in minutes."""

from timetable.model import Lesson
from timetable.overlap import conflicts, is_free, overlaps
from timetable.slots import find_slot

__all__ = [
    "Lesson",
    "conflicts",
    "find_slot",
    "is_free",
    "overlaps",
]

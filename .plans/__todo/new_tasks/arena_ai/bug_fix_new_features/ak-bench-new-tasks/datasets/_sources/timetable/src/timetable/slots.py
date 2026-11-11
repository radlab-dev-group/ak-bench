"""Finding a free slot for a new lesson. The rules are in this docstring;
the implementation is the task.

``find_slot(busy, duration, window_start, window_end, gap=0)`` returns the
earliest start minute ``s`` at which a lesson of ``duration`` minutes fits,
or ``None`` when no such minute exists.

``busy`` is an iterable of ``(start, end)`` half-open intervals. They may be
given in any order, may overlap each other, and may extend outside the
window; the result depends only on the intervals themselves.

A start ``s`` fits when all of the following hold:

- ``window_start <= s`` and ``s + duration <= window_end`` — the lesson
  lies inside the window;
- for every busy interval ``(busy_start, busy_end)``, the lesson keeps at
  least ``gap`` minutes from it: either ``s + duration <= busy_start - gap``
  or ``s >= busy_end + gap``. With ``gap=0`` this is exactly "does not
  overlap", so a lesson may start the minute a busy interval ends.

``duration`` must be positive, ``gap`` must not be negative, and
``window_end`` must be after ``window_start``; anything else raises
:class:`ValueError`. A ``duration`` longer than the window is not an error:
it simply fits nowhere, and the result is ``None``.
"""

from __future__ import annotations

from collections.abc import Iterable


def find_slot(
    busy: Iterable[tuple[int, int]],
    duration: int,
    window_start: int,
    window_end: int,
    gap: int = 0,
) -> int | None:
    """Return the earliest start minute that fits, under the rules above."""
    raise NotImplementedError("find_slot is specified in this module and not yet written")

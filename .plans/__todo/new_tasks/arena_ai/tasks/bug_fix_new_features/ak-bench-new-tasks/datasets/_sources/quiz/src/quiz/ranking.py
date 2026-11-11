"""Ranking finished attempts into a leaderboard. The rules are in this
docstring; the implementation is the task.

``rank_attempts(entries)`` returns one :class:`Ranked` per entry, best
first. Entries are ordered by:

1. ``total`` descending;
2. ``correct_count`` descending;
3. ``submitted_at`` ascending — an earlier submission wins a tie;
4. ``player`` ascending.

Ranks follow standard competition ranking ("1224"): two entries share a
rank when their ``total`` and ``correct_count`` are both equal, and the
next rank skips accordingly. ``submitted_at`` and ``player`` only order
entries that already share a rank; they never change the rank itself. So
the first entry has rank 1, and every other entry's rank is one plus the
number of entries with a strictly greater ``(total, correct_count)`` pair.

An empty input returns an empty list. Each entry is one attempt; the same
player may appear more than once and is ranked per entry.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from quiz.model import AttemptResult


@dataclass(frozen=True)
class Ranked:
    """One leaderboard row: the attempt and the rank it earned."""

    player: str
    total: int
    correct_count: int
    submitted_at: int
    rank: int


def rank_attempts(entries: Iterable[AttemptResult]) -> list[Ranked]:
    """Return the leaderboard under the rules in this module."""
    raise NotImplementedError("rank_attempts is specified in this module and not yet written")

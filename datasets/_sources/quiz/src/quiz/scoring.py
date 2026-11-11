"""Scoring an attempt, with a bonus for consecutive correct answers.

The rules, in the order they are applied:

1. A correct answer earns its question's ``points``. A wrong answer earns
   nothing.
2. Consecutive correct answers build a streak. A wrong answer ends the
   streak: the next correct answer starts a new streak at one.
3. From the third consecutive correct answer onward, each correct answer
   also earns a flat bonus of 25 points. The first and second answers of a
   streak earn no bonus, however long the streak later becomes.
4. The total is the base points plus the streak bonus. The best streak is
   the longest run of consecutive correct answers in the attempt.

An empty attempt scores zero everywhere.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from quiz.model import Question

#: bonus per correct answer from the third of a streak onward
STREAK_BONUS = 25
#: streak length at which the bonus starts
STREAK_THRESHOLD = 3


@dataclass(frozen=True)
class Score:
    """The scored result: every number is visible, nothing is folded away."""

    base_points: int
    streak_bonus: int
    total: int
    correct_count: int
    best_streak: int


def score_attempt(answers: Iterable[tuple[Question, str]]) -> Score:
    """Score ``(question, choice)`` pairs under the rules above."""
    base = 0
    bonus = 0
    correct = 0
    streak = 0
    best = 0
    for question, choice in answers:
        if choice == question.correct:
            correct += 1
            base += question.points
            streak += 1
            best = max(best, streak)
            if streak >= STREAK_THRESHOLD:
                bonus += STREAK_BONUS
        else:
            streak = 0
    return Score(
        base_points=base,
        streak_bonus=bonus,
        total=base + bonus,
        correct_count=correct,
        best_streak=best,
    )

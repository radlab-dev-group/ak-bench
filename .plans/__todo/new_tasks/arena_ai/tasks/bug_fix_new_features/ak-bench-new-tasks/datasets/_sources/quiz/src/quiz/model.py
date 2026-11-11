"""The records a quiz is made of."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    """One question: the correct choice and what it is worth."""

    question_id: str
    correct: str
    points: int = 100

    def __post_init__(self) -> None:
        if not self.question_id:
            raise ValueError("a question needs an id")
        if self.points <= 0:
            raise ValueError(f"points must be positive, got {self.points}")


@dataclass(frozen=True)
class AttemptResult:
    """One finished attempt, as the leaderboard sees it."""

    player: str
    total: int
    correct_count: int
    submitted_at: int

    def __post_init__(self) -> None:
        if not self.player:
            raise ValueError("an attempt needs a player")
        if self.total < 0:
            raise ValueError(f"total cannot be negative, got {self.total}")
        if self.correct_count < 0:
            raise ValueError(
                f"correct_count cannot be negative, got {self.correct_count}"
            )

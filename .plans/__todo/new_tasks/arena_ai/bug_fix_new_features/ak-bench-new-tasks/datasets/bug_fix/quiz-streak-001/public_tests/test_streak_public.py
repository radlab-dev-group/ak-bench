"""What a developer is told about this defect: the bonus starts at three.

These tests are visible to the agent. They state the rule and probe it at
the edges the hidden tests also care about, so an agent can find the defect
without being handed the exact assertions the evaluation uses.
"""

from __future__ import annotations

from quiz import Question, score_attempt


def correct(*ids: str):
    return [(Question(qid, "A", 100), "A") for qid in ids]


def test_two_in_a_row_earn_no_bonus():
    score = score_attempt(correct("Q1", "Q2"))
    assert score.streak_bonus == 0
    assert score.total == 200


def test_the_third_in_a_row_earns_the_bonus():
    score = score_attempt(correct("Q1", "Q2", "Q3"))
    assert score.streak_bonus == 25
    assert score.total == 325


def test_a_wrong_answer_resets_the_streak():
    answers = correct("Q1", "Q2") + [(Question("Q3", "A", 100), "B")] + correct("Q4")
    score = score_attempt(answers)
    assert score.streak_bonus == 0
    assert score.best_streak == 2

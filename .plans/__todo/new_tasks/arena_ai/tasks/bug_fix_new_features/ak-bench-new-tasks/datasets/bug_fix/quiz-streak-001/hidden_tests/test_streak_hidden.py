"""The defect, proven from every side the mutation can hide behind.

The hidden tests pass on the base commit and fail once the mutation is
applied; that is the contract of a bug-fix task (docs/DATASETS.md). They
cover streaks of two, three and more, the reset, and the fields the bonus
must not disturb.
"""

from __future__ import annotations

from quiz import Question, score_attempt


def correct(*ids: str, points: int = 100):
    return [(Question(qid, "A", points), "A") for qid in ids]


def wrong(qid: str):
    return [(Question(qid, "A", 100), "B")]


def test_a_streak_of_two_earns_no_bonus():
    score = score_attempt(correct("Q1", "Q2"))
    assert score.base_points == 200
    assert score.streak_bonus == 0
    assert score.total == 200
    assert score.best_streak == 2


def test_a_streak_of_three_earns_one_bonus():
    score = score_attempt(correct("Q1", "Q2", "Q3"))
    assert score.streak_bonus == 25
    assert score.total == 325
    assert score.best_streak == 3


def test_a_streak_of_five_earns_three_bonuses():
    score = score_attempt(correct("Q1", "Q2", "Q3", "Q4", "Q5"))
    assert score.streak_bonus == 75
    assert score.total == 575
    assert score.best_streak == 5


def test_the_bonus_uses_each_questions_own_points():
    answers = [
        (Question("Q1", "A", 50), "A"),
        (Question("Q2", "A", 200), "A"),
        (Question("Q3", "A", 10), "A"),
    ]
    score = score_attempt(answers)
    assert score.base_points == 260
    assert score.streak_bonus == 25
    assert score.total == 285


def test_a_wrong_answer_restarts_the_count():
    answers = correct("Q1", "Q2", "Q3") + wrong("Q4") + correct("Q5", "Q6")
    score = score_attempt(answers)
    assert score.streak_bonus == 25
    assert score.correct_count == 5
    assert score.best_streak == 3


def test_a_new_streak_needs_three_again():
    answers = correct("Q1", "Q2") + wrong("Q3") + correct("Q4", "Q5", "Q6")
    score = score_attempt(answers)
    assert score.streak_bonus == 25
    assert score.best_streak == 3


def test_two_separate_streaks_each_earn_their_bonus():
    answers = correct("Q1", "Q2", "Q3") + wrong("Q4") + correct("Q5", "Q6", "Q7")
    score = score_attempt(answers)
    assert score.streak_bonus == 50
    assert score.total == 650


def test_all_wrong_and_empty_attempts_have_no_bonus():
    assert score_attempt(wrong("Q1") + wrong("Q2")).streak_bonus == 0
    assert score_attempt([]).streak_bonus == 0

"""The finished part of the fixture: records and base scoring.

The suite deliberately never scores two correct answers in a row, so a
defect in when the streak bonus starts is invisible here.
"""

from __future__ import annotations

import pytest

from quiz import AttemptResult, Question, score_attempt


def test_a_question_needs_an_id_and_positive_points():
    with pytest.raises(ValueError):
        Question("", "A")
    with pytest.raises(ValueError):
        Question("Q1", "A", points=0)


def test_an_attempt_result_needs_a_player_and_non_negative_numbers():
    with pytest.raises(ValueError):
        AttemptResult("", 100, 1, 10)
    with pytest.raises(ValueError):
        AttemptResult("Ada", -1, 0, 10)
    with pytest.raises(ValueError):
        AttemptResult("Ada", 100, -1, 10)


def test_correct_answers_earn_their_points():
    score = score_attempt([(Question("Q1", "A", 100), "A")])
    assert score.base_points == 100
    assert score.total == 100
    assert score.correct_count == 1
    assert score.best_streak == 1


def test_wrong_answers_earn_nothing():
    score = score_attempt([(Question("Q1", "A", 100), "B")])
    assert score.base_points == 0
    assert score.total == 0
    assert score.correct_count == 0
    assert score.best_streak == 0


def test_separated_correct_answers_sum_without_a_bonus():
    answers = [
        (Question("Q1", "A", 100), "A"),
        (Question("Q2", "B", 50), "C"),
        (Question("Q3", "C", 200), "C"),
    ]
    score = score_attempt(answers)
    assert score.base_points == 300
    assert score.streak_bonus == 0
    assert score.total == 300
    assert score.correct_count == 2
    assert score.best_streak == 1


def test_an_empty_attempt_scores_zero():
    score = score_attempt([])
    assert score.total == 0
    assert score.correct_count == 0
    assert score.best_streak == 0

"""Harness: the test file must pass on the correct code and fail on the
defective code. The defective variant is a one-line mutation of the
fixture, swapped in for a second run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import quiz

TEST_REL = Path('tests/test_scoring_agent.py')
DEFECTIVE = {'src/quiz/scoring.py': '"""Scoring an attempt, with a bonus for consecutive correct answers.\n\nThe rules, in the order they are applied:\n\n1. A correct answer earns its question\'s ``points``. A wrong answer earns\n   nothing.\n2. Consecutive correct answers build a streak. A wrong answer ends the\n   streak: the next correct answer starts a new streak at one.\n3. From the third consecutive correct answer onward, each correct answer\n   also earns a flat bonus of 25 points. The first and second answers of a\n   streak earn no bonus, however long the streak later becomes.\n4. The total is the base points plus the streak bonus. The best streak is\n   the longest run of consecutive correct answers in the attempt.\n\nAn empty attempt scores zero everywhere.\n"""\n\nfrom __future__ import annotations\n\nfrom collections.abc import Iterable\nfrom dataclasses import dataclass\n\nfrom quiz.model import Question\n\n#: bonus per correct answer from the third of a streak onward\nSTREAK_BONUS = 25\n#: streak length at which the bonus starts\nSTREAK_THRESHOLD = 2\n\n\n@dataclass(frozen=True)\nclass Score:\n    """The scored result: every number is visible, nothing is folded away."""\n\n    base_points: int\n    streak_bonus: int\n    total: int\n    correct_count: int\n    best_streak: int\n\n\ndef score_attempt(answers: Iterable[tuple[Question, str]]) -> Score:\n    """Score ``(question, choice)`` pairs under the rules above."""\n    base = 0\n    bonus = 0\n    correct = 0\n    streak = 0\n    best = 0\n    for question, choice in answers:\n        if choice == question.correct:\n            correct += 1\n            base += question.points\n            streak += 1\n            best = max(best, streak)\n            if streak >= STREAK_THRESHOLD:\n                bonus += STREAK_BONUS\n        else:\n            streak = 0\n    return Score(\n        base_points=base,\n        streak_bonus=bonus,\n        total=base + bonus,\n        correct_count=correct,\n        best_streak=best,\n    )\n'}

SAMPLE = '"""Tests for quiz.scoring.score_attempt: streaks and the bonus."""\n\nfrom __future__ import annotations\n\nfrom quiz.model import Question\nfrom quiz.scoring import score_attempt\n\nQUESTIONS = [Question(f"q{i}", correct="a", points=100) for i in range(1, 6)]\n\n\ndef test_two_in_a_row_earns_no_bonus():\n    score = score_attempt([(QUESTIONS[0], "a"), (QUESTIONS[1], "a")])\n    assert score.base_points == 200\n    assert score.streak_bonus == 0\n    assert score.total == 200\n    assert score.best_streak == 2\n\n\ndef test_the_third_in_a_row_earns_the_bonus():\n    score = score_attempt([(QUESTIONS[0], "a"), (QUESTIONS[1], "a"), (QUESTIONS[2], "a")])\n    assert score.streak_bonus == 25\n    assert score.total == 325\n    assert score.best_streak == 3\n\n\ndef test_a_wrong_answer_resets_the_streak():\n    score = score_attempt(\n        [\n            (QUESTIONS[0], "a"),\n            (QUESTIONS[1], "a"),\n            (QUESTIONS[2], "x"),\n            (QUESTIONS[3], "a"),\n            (QUESTIONS[4], "a"),\n        ]\n    )\n    assert score.streak_bonus == 0\n    assert score.correct_count == 4\n    assert score.best_streak == 2\n\n\ndef test_an_empty_attempt_scores_zero():\n    score = score_attempt([])\n    assert score.total == 0\n    assert score.correct_count == 0\n    assert score.best_streak == 0\n'

def _repo_root() -> Path:
    return Path(quiz.__file__).resolve().parents[2]


def _run(defective: bool) -> subprocess.CompletedProcess:
    root = _repo_root()
    pass  # the sample is written into the copy below
    tmp = Path(tempfile.mkdtemp(prefix="agent-tests-"))
    work = tmp / "repo"
    shutil.copytree(
        root,
        work,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )
    (work / TEST_REL).parent.mkdir(parents=True, exist_ok=True)
    (work / TEST_REL).write_text(SAMPLE)
    if defective:
        for rel, content in DEFECTIVE.items():
            (work / rel).write_text(content)
    env = {**os.environ, "PYTHONPATH": str(work / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(work / TEST_REL)],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_tests_pass_on_the_correct_code():
    result = _run(defective=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_tests_fail_on_the_defective_code():
    result = _run(defective=True)
    assert result.returncode != 0, "the tests pass on defective code: they do not pin the behaviour"

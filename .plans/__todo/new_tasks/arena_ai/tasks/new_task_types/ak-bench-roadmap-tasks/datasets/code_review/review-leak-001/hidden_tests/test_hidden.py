"""The review, checked against the seeded issues in the PR."""

from __future__ import annotations

from pathlib import Path

import leakkit

REVIEW = Path(leakkit.__file__).resolve().parents[2] / "REVIEW.md"

ISSUES = [['close', 'leak', 'context manager', 'with '], ['bare except', 'except:', 'too broad', 'swallows']]


def _review_text() -> str:
    assert REVIEW.is_file(), "REVIEW.md is missing at the repository root"
    text = REVIEW.read_text(encoding="utf-8")
    assert len(text) >= 200, "the review is too short to cover the PR"
    return text.lower()

def test_finds_issue_1():
    text = _review_text()
    assert any(keyword in text for keyword in ISSUES[0]), (
        f"issue 1 is not mentioned in REVIEW.md"
    )

def test_finds_issue_2():
    text = _review_text()
    assert any(keyword in text for keyword in ISSUES[1]), (
        f"issue 2 is not mentioned in REVIEW.md"
    )

"""The review, checked against the seeded issues in the PR."""

from __future__ import annotations

from pathlib import Path

import largekit

REVIEW = Path(largekit.__file__).resolve().parents[2] / "REVIEW.md"

ISSUES = [['secret', 'hardcoded', 'api key', 'api_key'], ['eval'], ['off-by-one', 'off by one', 'ceil', 'rounding', 'floor'], ['test']]


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

def test_finds_issue_3():
    text = _review_text()
    assert any(keyword in text for keyword in ISSUES[2]), (
        f"issue 3 is not mentioned in REVIEW.md"
    )

def test_finds_issue_4():
    text = _review_text()
    assert any(keyword in text for keyword in ISSUES[3]), (
        f"issue 4 is not mentioned in REVIEW.md"
    )

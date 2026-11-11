"""The review, in miniature: it exists and names real issues."""

from __future__ import annotations

from pathlib import Path

import racekit

REVIEW = Path(racekit.__file__).resolve().parents[2] / "REVIEW.md"
KEYWORDS = ['atomic', 'check-then-act', 'default argument', 'lock', 'mutable default', 'race', 'shared', 'thread']


def test_a_review_exists_and_names_an_issue():
    assert REVIEW.is_file(), "REVIEW.md is missing at the repository root"
    text = REVIEW.read_text(encoding="utf-8").lower()
    assert len(text) >= 200
    assert any(keyword in text for keyword in KEYWORDS)

"""Hidden tests for wordcount-001. Never copied into an agent workspace."""

from __future__ import annotations

from wordcount import count_words, top_words


def test_empty_string_has_no_words():
    assert count_words("") == 0


def test_whitespace_only_has_no_words():
    assert count_words("   ") == 0
    assert count_words("\n\n \t ") == 0


def test_repeated_whitespace_counts_once_between_words():
    assert count_words("alpha    beta") == 2


def test_tabs_and_newlines_separate_words():
    assert count_words("alpha\tbeta\ngamma") == 3


def test_top_words_still_works():
    assert top_words("x y x z x", limit=2) == [("x", 3), ("y", 1)]

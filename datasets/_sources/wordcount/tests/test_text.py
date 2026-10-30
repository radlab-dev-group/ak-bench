from __future__ import annotations

from wordcount import count_words, top_words


def test_counts_plain_words():
    assert count_words("one two three") == 3


def test_top_words_returns_most_frequent():
    assert top_words("a b a", limit=1) == [("a", 2)]

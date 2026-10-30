"""Public tests shipped with the task. They pass both before and after the
defect, so they tell the agent nothing it did not already know."""

from __future__ import annotations

from wordcount import count_words


def test_counts_words_separated_by_single_spaces():
    assert count_words("the quick brown fox") == 4

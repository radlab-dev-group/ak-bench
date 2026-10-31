"""Public tests shipped with the task.

They cover the examples from the specification, so they fail on the base commit
(the feature is missing) and pass once it is implemented. They are a subset of
the contract, not the whole of it.
"""

from __future__ import annotations

from textkit import slugify


def test_lowercases_and_joins_words():
    assert slugify("Hello World") == "hello-world"


def test_collapses_runs_of_separators():
    assert slugify("one -- two") == "one-two"


def test_empty_input_has_no_slug():
    assert slugify("") == ""

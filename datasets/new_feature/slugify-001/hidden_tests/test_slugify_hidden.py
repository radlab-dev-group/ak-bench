"""Hidden tests for slugify-001. Never copied into an agent workspace."""

from __future__ import annotations

from textkit import casefold_word, slugify


def test_words_are_lowercased_and_joined_with_a_hyphen():
    assert slugify("Hello World") == "hello-world"


def test_punctuation_acts_as_a_separator():
    assert slugify("Hello, World!") == "hello-world"


def test_runs_of_separators_collapse_to_one():
    assert slugify("one -- two ___ three") == "one-two-three"


def test_leading_and_trailing_separators_are_removed():
    assert slugify("  --Trimmed--  ") == "trimmed"


def test_digits_are_kept():
    assert slugify("AK-Bench 2026") == "ak-bench-2026"


def test_non_ascii_letters_are_separators_not_letters_to_transliterate():
    assert slugify("Zażółć") == "za"
    assert slugify("Zażółć gęślami") == "za-g-lami"


def test_input_without_letters_or_digits_is_empty():
    assert slugify("") == ""
    assert slugify("!!!") == ""
    assert slugify("   ~~~   ") == ""


def test_separator_is_inserted_verbatim():
    assert slugify("Hello World", separator="_") == "hello_world"


def test_slugifying_a_slug_changes_nothing():
    once = slugify("  Release   Notes!! ")
    assert once == "release-notes"
    assert slugify(once) == once


def test_the_rest_of_the_package_still_works():
    assert casefold_word("HeLLo") == "hello"

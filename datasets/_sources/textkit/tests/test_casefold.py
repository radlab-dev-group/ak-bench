from __future__ import annotations

from textkit import casefold_word


def test_casefold_lowers_the_word():
    assert casefold_word("HeLLo") == "hello"


def test_casefold_keeps_attached_punctuation():
    assert casefold_word("Don't") == "don't"

"""The finished part of the fixture: search behaviour.

These tests pin the behaviour the index must preserve.
"""

from __future__ import annotations

from searchkit import search

DOCS = ["the cat sat", "a dog ran", "the cat ran"]


def test_search_finds_the_documents():
    assert search(DOCS, "cat") == [0, 2]
    assert search(DOCS, "dog") == [1]
    assert search(DOCS, "fish") == []

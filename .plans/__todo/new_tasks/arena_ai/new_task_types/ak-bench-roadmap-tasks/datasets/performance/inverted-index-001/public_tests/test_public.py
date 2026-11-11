"""The index, in miniature: mapping plus index-only search."""

from __future__ import annotations

from searchkit import search
from searchkit.index import build_index, search as index_search

DOCS = ["the cat sat", "a dog ran", "the cat ran"]


def test_build_index_maps_words_to_documents():
    index = build_index(DOCS)
    assert index["cat"] == [0, 2]
    assert index["dog"] == [1]
    assert index["the"] == [0, 2]


def test_index_search_matches_the_scan():
    index = build_index(DOCS)
    assert index_search(index, "cat") == search(DOCS, "cat") == [0, 2]
    assert index_search(index, "fish") == []

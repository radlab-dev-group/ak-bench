"""The index, proven: mapping, agreement with the scan, index-only search.

The search must answer from the index alone: it works after the
documents are gone and it reflects mutations of the index, which a
document scan could never do.
"""

from __future__ import annotations

from searchkit import search
from searchkit.index import build_index, search as index_search

DOCS = ["the cat sat", "a dog ran", "the cat ran", "the dog sat"]


def test_build_index_maps_every_word():
    index = build_index(DOCS)
    assert index["cat"] == [0, 2]
    assert index["dog"] == [1, 3]
    assert index["the"] == [0, 2, 3]
    assert index["sat"] == [0, 3]
    assert index["ran"] == [1, 2]
    assert index["a"] == [1]


def test_build_index_lists_each_document_once_per_word():
    index = build_index(["cat cat cat", "cat"])
    assert index["cat"] == [0, 1]


def test_index_search_agrees_with_the_scan():
    index = build_index(DOCS)
    for term in ["cat", "dog", "the", "sat", "ran", "fish"]:
        assert index_search(index, term) == search(DOCS, term)


def test_index_search_needs_only_the_index():
    docs = ["the cat sat", "a dog ran"]
    index = build_index(docs)
    del docs  # the documents are gone; the index must still answer
    assert index_search(index, "cat") == [0]
    index["zebra"] = [99]  # a mutation only an index lookup can see
    assert index_search(index, "zebra") == [99]

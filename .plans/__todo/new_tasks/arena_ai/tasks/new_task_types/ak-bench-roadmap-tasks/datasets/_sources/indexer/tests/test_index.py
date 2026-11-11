"""The finished part of the fixture: adding and searching.

The suite deliberately never searches after deleting the only document
with that term, so a stale-index defect is invisible here.
"""

from __future__ import annotations

from indexer import Indexer


def test_search_finds_added_documents():
    index = Indexer()
    index.add("d1", {"alpha", "beta"})
    index.add("d2", {"beta", "gamma"})
    assert index.search("alpha") == ["d1"]
    assert index.search("beta") == ["d1", "d2"]
    assert index.search("delta") == []


def test_replacing_a_document_updates_the_index():
    index = Indexer()
    index.add("d1", {"alpha"})
    index.add("d1", {"beta"})
    assert index.search("alpha") == []
    assert index.search("beta") == ["d1"]


def test_deleting_an_unknown_document_is_a_no_op():
    index = Indexer()
    index.delete("nope")
    assert index.search("alpha") == []

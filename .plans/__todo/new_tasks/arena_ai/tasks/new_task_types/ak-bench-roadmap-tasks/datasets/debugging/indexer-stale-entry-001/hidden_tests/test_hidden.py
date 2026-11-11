"""The failing scenario, proven from every side.

These tests fail on the base commit (the defect is in the base code) and
pass once the index is repaired.
"""

from __future__ import annotations

from indexer import Indexer


def test_a_deleted_document_is_not_found():
    index = Indexer()
    index.add("d1", {"alpha"})
    index.delete("d1")
    assert index.search("alpha") == []


def test_a_surviving_document_is_still_found():
    index = Indexer()
    index.add("d1", {"alpha"})
    index.add("d2", {"alpha"})
    index.delete("d1")
    assert index.search("alpha") == ["d2"]


def test_a_deleted_document_is_not_found_for_any_of_its_terms():
    index = Indexer()
    index.add("d1", {"alpha", "beta"})
    index.delete("d1")
    assert index.search("alpha") == []
    assert index.search("beta") == []


def test_readding_a_deleted_document_makes_it_searchable():
    index = Indexer()
    index.add("d1", {"alpha"})
    index.delete("d1")
    index.add("d1", {"alpha"})
    assert index.search("alpha") == ["d1"]


def test_replacing_a_document_still_updates_the_index():
    index = Indexer()
    index.add("d1", {"alpha"})
    index.add("d1", {"beta"})
    assert index.search("alpha") == []
    assert index.search("beta") == ["d1"]


def test_deleting_twice_is_harmless():
    index = Indexer()
    index.add("d1", {"alpha"})
    index.delete("d1")
    index.delete("d1")
    assert index.search("alpha") == []

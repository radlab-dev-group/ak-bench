"""The symptom a developer can reproduce: search finds a deleted document."""

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

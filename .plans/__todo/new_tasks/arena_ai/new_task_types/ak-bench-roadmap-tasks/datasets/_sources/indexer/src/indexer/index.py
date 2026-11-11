"""Indexing documents by term.

A document is a set of terms. Searching returns the ids of the live
documents that contain the term, sorted. Deleting a document removes it
from the index entirely: a deleted document must never be found again,
unless it is added again.
"""

from __future__ import annotations


class Indexer:
    """Documents by term, with deletion."""

    def __init__(self) -> None:
        self._docs: dict[str, set[str]] = {}
        self._index: dict[str, set[str]] = {}

    def add(self, doc_id: str, terms: set[str]) -> None:
        """Index a document, replacing any previous version of it."""
        old_terms = self._docs.get(doc_id)
        if old_terms is not None:
            for term in old_terms:
                holders = self._index.get(term)
                if holders is not None:
                    holders.discard(doc_id)
        self._docs[doc_id] = set(terms)
        for term in terms:
            self._index.setdefault(term, set()).add(doc_id)

    def delete(self, doc_id: str) -> None:
        """Remove a document from the index entirely."""
        self._docs.pop(doc_id, None)

    def search(self, term: str) -> list[str]:
        """The sorted ids of live documents containing ``term``."""
        return sorted(self._index.get(term, set()))

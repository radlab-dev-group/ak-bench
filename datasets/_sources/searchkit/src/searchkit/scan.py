"""Searching documents by scanning them all."""

from __future__ import annotations


def search(docs: list[str], term: str) -> list[int]:
    """The ids of the documents containing ``term``, in order."""
    return [
        doc_id
        for doc_id, doc in enumerate(docs)
        if term in doc.split()
    ]

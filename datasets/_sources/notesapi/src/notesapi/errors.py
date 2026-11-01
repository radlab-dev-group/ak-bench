"""The exceptions the service raises; each says what it is, not where it came from."""

from __future__ import annotations


class UnknownNote(KeyError):
    """A note id the store does not hold."""


class Conflict(Exception):
    """Two notes disagree about the same id in a way the merge rules cannot resolve."""

    def __init__(self, note_id: str, reason: str) -> None:
        super().__init__(f"{note_id}: {reason}")
        self.note_id = note_id
        self.reason = reason

"""Implement the changelog protocol described in README.md.

visible contains the last emitted Result for each still-live address. Reconcile
against a complete ready() view: first retract changed/disappeared old rows in
address order, then upsert changed/new rows in address order. Unchanged rows
emit nothing. Sequence numbers begin at 1 and are never reused after restore.
Finalization forgets visible rows silently AFTER their last reconciliation.
"""

from .model import Change, Result


class Changelog:
    def __init__(self) -> None:
        self.visible: dict[tuple[str, str, int, int], Result] = {}
        self.sequence = 0

    def reconcile(self, ready: list[Result]) -> list[Change]:
        raise NotImplementedError("compute ordered retractions and upserts")

    def forget(self, addresses: set[tuple[str, str, int, int]]) -> None:
        raise NotImplementedError("forget finalized rows without retracting their output")

    def document(self) -> dict:
        raise NotImplementedError("encode output sequence and visible rows")

    @classmethod
    def restore(cls, document: dict) -> "Changelog":
        raise NotImplementedError("restore output sequence and visible rows")

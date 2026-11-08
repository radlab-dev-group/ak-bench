"""Optimistic transactions with read-set fencing.

A transaction reads keys, remembers the generation it read each one at, and
commits only if none of them moved. A write that lands on a read key between
the read and the commit is not a conflict the caller has to detect: the store
detects it, aborts the transaction, and the caller sees
:class:`~atlas.errors.StaleGenerationError`.

Aborting releases the transaction's lease. That is not an optimisation; a
transaction that holds a lease it will never use is a key other callers
cannot write, and a cluster full of aborted-but-still-holding transactions
is a cluster that has stopped accepting writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import StaleGenerationError
from .fencing import FenceBook

READ = "read"
WRITE = "write"


@dataclass
class Transaction:
    """One unit of work against a fenced store."""

    writer: str
    fence: FenceBook
    planned_epoch: int
    read_set: dict[str, int] = field(default_factory=dict)
    writes: list[tuple[str, Any]] = field(default_factory=list)
    state: str = "open"

    def read(self, key: str, generation: int) -> int:
        """Record a read at ``generation``; return the generation for the caller.

        Re-reading a key the transaction already read is an error: the first
        read is the one the commit will fence on, and silently adopting a
        later one would widen the window a write can slip through.
        """

        if self.state != "open":
            raise StaleGenerationError(key, self.read_set.get(key, 0), generation)
        if key in self.read_set:
            if self.read_set[key] != generation:
                raise StaleGenerationError(key, self.read_set[key], generation)
            return self.read_set[key]
        self.read_set[key] = generation
        return generation

    def write(self, key: str, value: Any) -> None:
        if self.state != "open":
            raise StaleGenerationError(key, self.read_set.get(key, 0), 0)
        if key not in self.read_set:
            self.read_set[key] = -1
        self.writes.append((key, value))

    def commit(self, generations_now) -> list[tuple[str, Any]]:
        """Check the read set against ``generations_now`` and return the writes.

        ``generations_now`` maps key to its current generation. Every key the
        transaction read at generation ``g`` must still be at ``g``. A key
        written but never read is checked against ``-1`` and passes, which is
        how a create-without-read commits.
        """

        if self.state != "open":
            raise StaleGenerationError("<txn>", self.state, "open")
        for key, generation in sorted(self.read_set.items()):
            if generation < 0:
                continue
            current = generations_now(key)
            if current != generation:
                self.abort()
                raise StaleGenerationError(key, generation, current)
        self.state = "committed"
        return list(self.writes)

    def abort(self) -> None:
        if self.state == "aborted":
            return
        self.state = "aborted"
        for key in self.read_set:
            self.fence.release(key)
        self.read_set.clear()
        self.writes.clear()

    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is not None and self.state == "open":
            self.abort()

"""Provenance: which write produced which state, and why.

.. note::
   **This feature is not implemented.** The classes below declare the
   contract; every method that would do work raises ``NotImplementedError``.
   The contract is complete and normative: it says what a caller may expect,
   in the order the expectations hold, and an implementation is judged against
   it, not against these stubs. See ``SPEC.md`` section 9 for the acceptance
   rules and ``docs/lineage.md`` for the reasoning behind them.

Lineage answers three questions about a key:

* **why is this the value** — which write is currently visible for the key;
* **what caused it** — the causal parents of that write, which is the write
  whose generation the writer read, plus a repair or a migration that moved a
  version onto this replica;
* **what did it cause** — the reverse edge, which is what a bad write is
  traced forward through.

Edges are identified by the pair of ``(key, generation)`` endpoints and are
therefore idempotent: recording the same edge twice is one edge, and a replay
of a log that already produced lineage must not double it. Causes are typed:

``caused_by``      a write that read a prior generation of the same key;
``replicated_by``  a quorum write that landed on a second replica;
``repaired_by``    read repair or anti-entropy wrote a peer's version forward;
``migrated_by``    a rebalance moved the record to a different replica;
``restored_by``    recovery applied the record from the log after a restart.

The recorder is a pure book-keeping object: it never reads storage, and the
store tells it what happened. That separation is what lets lineage be turned
off without changing any other behaviour, and what makes a lineage bug a
lineage bug rather than a storage bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .values import Record

#: The five documented edge kinds. An implementation may not add a sixth: a
#: cause that none of these names is a cause the recorder cannot explain.
CAUSE_WRITE = "caused_by"
CAUSE_REPLICATE = "replicated_by"
CAUSE_REPAIR = "repaired_by"
CAUSE_MIGRATE = "migrated_by"
CAUSE_RESTORE = "restored_by"

CAUSE_KINDS = (
    CAUSE_WRITE,
    CAUSE_REPLICATE,
    CAUSE_REPAIR,
    CAUSE_MIGRATE,
    CAUSE_RESTORE,
)


@dataclass(frozen=True)
class Node:
    """One point in the provenance graph: a key at a generation, on a replica."""

    key: str
    generation: int
    replica: str = ""
    lsn: int = 0

    @property
    def identity(self) -> str:
        return f"{self.key}@{self.generation}"

    def render(self) -> str:
        return f"{self.identity}#{self.replica or 'any'}"


@dataclass(frozen=True)
class Edge:
    """A directed cause: ``child`` exists because of ``parent``."""

    parent: Node
    child: Node
    kind: str
    author: str = ""
    lsn: int = 0

    def __post_init__(self) -> None:
        if self.kind not in CAUSE_KINDS:
            raise ValueError(f"unknown cause kind {self.kind!r}; expected {CAUSE_KINDS}")


@dataclass
class LineageGraph:
    """The edges recorded so far, indexed both ways.

    Implementations must keep the two indexes consistent: an edge present in
    one and missing from the other is a bug that shows up as an asymmetric
    answer to ``why`` and ``whence``.
    """

    edges: list[Edge] = field(default_factory=list)

    def add(self, edge: Edge) -> bool:  # pragma: no cover - contract stub
        """Record ``edge``; return ``False`` when the same edge was already there."""

        raise NotImplementedError("lineage capture is not implemented")

    def why(self, key: str, generation: int | None = None) -> list[Edge]:  # pragma: no cover
        """Edges whose child is this version, ordered by LSN then parent identity."""

        raise NotImplementedError("lineage capture is not implemented")

    def whence(self, key: str, generation: int) -> list[Edge]:  # pragma: no cover
        """Edges whose parent is this version, ordered by LSN then child identity."""

        raise NotImplementedError("lineage capture is not implemented")

    def history(self, key: str) -> list[Edge]:  # pragma: no cover
        """Every edge that mentions ``key``, in the order it was recorded."""

        raise NotImplementedError("lineage capture is not implemented")

    def reachable(self, key: str, generation: int, *, depth: int | None = None) -> list[Node]:
        """The transitive closure of parents of a version, nearest first."""

        raise NotImplementedError("lineage capture is not implemented")

    def __len__(self) -> int:
        return len(self.edges)


class LineageRecorder:
    """What the store talks to. One recorder per cluster.

    The store calls :meth:`record_write` on every accepted write, and the
    implementation is expected to derive the cause itself: a write that
    offered a generation of a key it had read produces a ``caused_by`` edge
    to that generation, and a write with no offered generation is a root.
    """

    def __init__(self, *, enabled: bool = True, max_edges: int = 100_000) -> None:
        self.enabled = bool(enabled)
        self.max_edges = int(max_edges)
        self.graph = LineageGraph()

    def record_write(
        self,
        key: str,
        record: Record,
        *,
        author: str,
        cause: Node | None = None,
        replica: str = "",
    ) -> Edge | None:  # pragma: no cover - contract stub
        """Record the provenance of one accepted write.

        ``cause`` is the version the writer read, when it read one. Returns
        the edge recorded, or ``None`` when the recorder is disabled.
        """

        raise NotImplementedError("lineage capture is not implemented")

    def record_replication(
        self, key: str, record: Record, *, source: str, destination: str
    ) -> Edge | None:  # pragma: no cover
        raise NotImplementedError("lineage capture is not implemented")

    def record_repair(
        self, key: str, winner: Record, *, source: str, destination: str
    ) -> Edge | None:  # pragma: no cover
        raise NotImplementedError("lineage capture is not implemented")

    def record_migration(
        self, key: str, record: Record, *, source: str, destination: str
    ) -> Edge | None:  # pragma: no cover
        raise NotImplementedError("lineage capture is not implemented")

    def record_restore(self, key: str, record: Record, *, replica: str) -> Edge | None:
        """Called by recovery for every record it applied from the log."""

        raise NotImplementedError("lineage capture is not implemented")

    def trace(self, key: str, generation: int | None = None) -> list[Node]:  # pragma: no cover
        """The chain of causes leading to a version, oldest first, no repeats."""

        raise NotImplementedError("lineage capture is not implemented")

    def explain(self, key: str, generation: int | None = None) -> str:
        """A human-readable rendering of :meth:`trace`, one edge per line."""

        raise NotImplementedError("lineage capture is not implemented")

    def export(self) -> list[dict]:  # pragma: no cover
        """Every edge as a plain dictionary, ordered by LSN then identity."""

        raise NotImplementedError("lineage capture is not implemented")

    def clear(self) -> None:
        self.graph = LineageGraph()

"""Provenance: which write produced which state, and why.

The contract is in ``SPEC.md`` section 9 and the reasoning in
``docs/lineage.md``. This module is the implementation of that contract: a
graph of edges between ``(key, generation)`` nodes, five edge kinds,
idempotent under replay, and an observer that never reads storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .values import Record

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

    @property
    def identity(self) -> str:
        return f"{self.parent.identity} -> {self.child.identity} ({self.kind})"


@dataclass
class LineageGraph:
    """The edges recorded so far, indexed both ways.

    The two indexes stay consistent by construction: :meth:`add` writes to
    both, and nothing else mutates either.
    """

    edges: list[Edge] = field(default_factory=list)
    _why: dict[tuple[str, int], list[Edge]] = field(default_factory=dict, repr=False)
    _whence: dict[tuple[str, int], list[Edge]] = field(default_factory=dict, repr=False)

    def add(self, edge: Edge) -> bool:
        """Record ``edge``; return ``False`` when the same edge was already there."""

        for existing in self.edges:
            if (
                existing.parent.identity == edge.parent.identity
                and existing.child.identity == edge.child.identity
                and existing.kind == edge.kind
            ):
                return False
        self.edges.append(edge)
        self._why.setdefault((edge.child.key, edge.child.generation), []).append(edge)
        self._whence.setdefault((edge.parent.key, edge.parent.generation), []).append(edge)
        return True

    def why(self, key: str, generation: int | None = None) -> list[Edge]:
        if generation is None:
            found = [
                edge for edges in self._why.values() for edge in edges if edge.child.key == key
            ]
            return sorted(found, key=lambda edge: (edge.lsn, edge.parent.identity))
        return sorted(
            self._why.get((key, generation), []),
            key=lambda edge: (edge.lsn, edge.parent.identity),
        )

    def whence(self, key: str, generation: int) -> list[Edge]:
        return sorted(
            self._whence.get((key, generation), []),
            key=lambda edge: (edge.lsn, edge.child.identity),
        )

    def history(self, key: str) -> list[Edge]:
        return [edge for edge in self.edges if edge.parent.key == key or edge.child.key == key]

    def reachable(self, key: str, generation: int, *, depth: int | None = None) -> list[Node]:
        """The transitive closure of parents of a version, nearest first."""

        seen: set[tuple[str, int]] = set()
        result: list[Node] = []
        frontier = [(key, generation)]
        steps = 0
        while frontier:
            next_frontier: list[tuple[str, int]] = []
            for k, g in frontier:
                if (k, g) in seen:
                    continue
                seen.add((k, g))
                for edge in self._why.get((k, g), []):
                    parent = edge.parent
                    if (parent.key, parent.generation) not in seen:
                        result.append(parent)
                        next_frontier.append((parent.key, parent.generation))
            frontier = next_frontier
            steps += 1
            if depth is not None and steps > depth:
                break
        return result

    def __len__(self) -> int:
        return len(self.edges)


class LineageRecorder:
    """What the store talks to. One recorder per cluster.

    The store calls :meth:`record_write` on every accepted write and passes
    the version the writer read as ``cause``, or ``None`` for a root write.
    The recorder derives the edge; it does not construct one from a caller's
    hand, which is what keeps the graph a statement about the store and not
    about the caller.
    """

    def __init__(self, *, enabled: bool = True, max_edges: int = 100_000) -> None:
        self.enabled = bool(enabled)
        self.max_edges = int(max_edges)
        self.graph = LineageGraph()
        self._saturated = False

    def _child(self, key: str, record: Record, replica: str) -> Node:
        return Node(key=key, generation=record.generation, replica=replica, lsn=record.lsn)

    def _add(self, parent: Node, child: Node, kind: str, author: str, lsn: int) -> Edge | None:
        if not self.enabled or self._saturated:
            return None
        if len(self.graph) >= self.max_edges:
            self._saturated = True
            return None
        edge = Edge(parent=parent, child=child, kind=kind, author=author, lsn=lsn)
        self.graph.add(edge)
        if len(self.graph) >= self.max_edges:
            self._saturated = True
        return edge

    def record_write(
        self,
        key: str,
        record: Record,
        *,
        author: str,
        cause: Node | None = None,
        replica: str = "",
    ) -> Edge | None:
        """Record the provenance of one accepted write.

        A write that read a prior generation of the key produces a
        ``caused_by`` edge to that generation. A write with no cause is a
        root: it records no edge.
        """

        if not self.enabled:
            return None
        child = self._child(key, record, replica)
        if cause is not None:
            return self._add(cause, child, CAUSE_WRITE, author, record.lsn)
        return None

    def record_replication(
        self, key: str, record: Record, *, source: str, destination: str
    ) -> Edge | None:
        if not self.enabled:
            return None
        source_node = Node(key=key, generation=record.generation, replica=source, lsn=record.lsn)
        destination_node = Node(key=key, generation=record.generation, replica=destination, lsn=record.lsn)
        return self._add(source_node, destination_node, CAUSE_REPLICATE, "", record.lsn)

    def record_repair(
        self, key: str, winner: Record, *, source: str, destination: str
    ) -> Edge | None:
        if not self.enabled:
            return None
        source_node = Node(key=key, generation=winner.generation, replica=source, lsn=winner.lsn)
        destination_node = Node(key=key, generation=winner.generation, replica=destination, lsn=winner.lsn)
        return self._add(source_node, destination_node, CAUSE_REPAIR, "", winner.lsn)

    def record_migration(
        self, key: str, record: Record, *, source: str, destination: str
    ) -> Edge | None:
        if not self.enabled:
            return None
        source_node = Node(key=key, generation=record.generation, replica=source, lsn=record.lsn)
        destination_node = Node(key=key, generation=record.generation, replica=destination, lsn=record.lsn)
        return self._add(source_node, destination_node, CAUSE_MIGRATE, "", record.lsn)

    def record_restore(self, key: str, record: Record, *, replica: str) -> Edge | None:
        """Called by recovery for every record it applied from the log."""

        if not self.enabled:
            return None
        child = self._child(key, record, replica)
        parent = Node(key=key, generation=max(1, record.generation - 1), replica=replica, lsn=record.lsn)
        return self._add(parent, child, CAUSE_RESTORE, "", record.lsn)

    def trace(self, key: str, generation: int | None = None) -> list[Node]:
        """The chain of causes leading to a version, oldest first, no repeats."""

        if generation is None:
            versions = sorted(
                {
                    (edge.child.key, edge.child.generation)
                    for edge in self.graph.edges
                    if edge.child.key == key
                }
            )
            if not versions:
                return []
            generation = versions[-1][1]
        reachable = self.graph.reachable(key, generation)
        result: list[Node] = []
        seen: set[tuple[str, int]] = set()
        for node in reversed(reachable):
            if (node.key, node.generation) not in seen:
                seen.add((node.key, node.generation))
                result.append(node)
        result.append(Node(key=key, generation=generation))
        return result

    def explain(self, key: str, generation: int | None = None) -> str:
        """A human-readable rendering of :meth:`trace`, one edge per line."""

        if generation is None:
            versions = sorted(
                {
                    (edge.child.key, edge.child.generation)
                    for edge in self.graph.edges
                    if edge.child.key == key
                }
            )
            if not versions:
                return f"{key}: no recorded history"
            generation = versions[-1][1]
        chain = self.trace(key, generation)
        lines = [f"{key}@{generation}:"]
        for index, node in enumerate(chain):
            marker = "  " if index else "-> "
            lines.append(f"{marker}{node.render()}")
        return "\n".join(lines)

    def export(self) -> list[dict]:
        """Every edge as a plain dictionary, ordered by LSN then by identity."""

        ordered = sorted(
            self.graph.edges,
            key=lambda edge: (edge.lsn, edge.parent.identity, edge.child.identity),
        )
        return [
            {
                "parent": edge.parent.identity,
                "child": edge.child.identity,
                "kind": edge.kind,
                "author": edge.author,
                "lsn": edge.lsn,
            }
            for edge in ordered
        ]

    def clear(self) -> None:
        self.graph = LineageGraph()
        self._saturated = False

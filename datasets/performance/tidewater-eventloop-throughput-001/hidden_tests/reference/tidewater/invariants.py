"""Safety invariants, checked after every tick.

Raft promises five safety properties; the simulator checks all of them plus
one that only matters once membership can change. Each check raises
:class:`SafetyViolation` with a ``kind`` from the closed set
:data:`VIOLATION_KINDS` and a ``detail`` string that names the nodes, the
index and the terms involved. The set of kinds is closed on purpose: a task
that mutates the simulator must produce one of these six and nothing else,
so that a test can assert the *kind* without pinning the wording.

=====================  =====================================================
kind                   what it means
=====================  =====================================================
``election_safety``    two different nodes were leader in the same term
``log_matching``       two logs agree on ``(index, term)`` at some index but
                       differ at an earlier one
``leader_completeness`` a leader's log lacks (or holds a different version
                       of) an entry committed in an earlier term
``state_machine_safety`` a node applied, at some index, an entry different
                       from the one another node applied (or committed) there
``commit_regression``  a node's commit index went backwards without a restart
``membership_split``   two configurations alive at the same time admit two
                       disjoint majorities
=====================  =====================================================

The checker is a :class:`InvariantMonitor` with memory: it remembers which
node led in which term, what was committed at each index, and what each
node applied, because four of the six properties are statements about
history, not about the current state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from .errors import TidewaterError
from .membership import Configuration, disjoint_quorums_possible

if TYPE_CHECKING:  # pragma: no cover
    from .node import Node

ELECTION_SAFETY = "election_safety"
LOG_MATCHING = "log_matching"
LEADER_COMPLETENESS = "leader_completeness"
STATE_MACHINE_SAFETY = "state_machine_safety"
COMMIT_REGRESSION = "commit_regression"
MEMBERSHIP_SPLIT = "membership_split"

#: The closed set. Adding a kind is a change to the safety contract.
VIOLATION_KINDS: tuple[str, ...] = (
    ELECTION_SAFETY,
    LOG_MATCHING,
    LEADER_COMPLETENESS,
    STATE_MACHINE_SAFETY,
    COMMIT_REGRESSION,
    MEMBERSHIP_SPLIT,
)


class SafetyViolation(TidewaterError):
    """A safety property was broken. ``kind`` is one of :data:`VIOLATION_KINDS`."""

    def __init__(self, kind: str, detail: str, tick: int | None = None) -> None:
        if kind not in VIOLATION_KINDS:
            raise ValueError(f"unknown violation kind {kind!r}; the contract knows {VIOLATION_KINDS}")
        self.kind = kind
        self.detail = detail
        self.tick = tick
        where = f" at tick {tick}" if tick is not None else ""
        super().__init__(f"{kind}{where}: {detail}")


@dataclass(frozen=True)
class CommittedRecord:
    index: int
    term: int
    summary: str
    by: str
    tick: int


@dataclass
class InvariantMonitor:
    """History-aware checker. One per cluster; ``check`` is called once per
    tick with the live node objects, after deliveries and ticks and before
    the clock advances."""

    leaders_by_term: dict[int, str] = field(default_factory=dict)
    committed: dict[int, CommittedRecord] = field(default_factory=dict)
    applied: dict[int, tuple[int, str]] = field(default_factory=dict)
    last_commit_index: dict[str, int] = field(default_factory=dict)
    seen_restarts: dict[str, int] = field(default_factory=dict)
    checks: int = 0
    enabled: tuple[str, ...] = VIOLATION_KINDS

    # -- entry point -----------------------------------------------------

    def check(self, nodes: Iterable["Node"], tick: int) -> None:
        self.checks += 1
        live = [n for n in sorted(nodes, key=lambda n: n.node_id) if n.alive]
        if ELECTION_SAFETY in self.enabled:
            self.check_election_safety(live, tick)
        if COMMIT_REGRESSION in self.enabled:
            self.check_commit_regression(live, tick)
        self.record_commits(live, tick)
        if LOG_MATCHING in self.enabled:
            self.check_log_matching(live, tick)
        if LEADER_COMPLETENESS in self.enabled:
            self.check_leader_completeness(live, tick)
        if STATE_MACHINE_SAFETY in self.enabled:
            self.check_state_machine_safety(live, tick)
        if MEMBERSHIP_SPLIT in self.enabled:
            self.check_membership_split(live, tick)

    # -- individual properties ------------------------------------------

    def check_election_safety(self, live: list["Node"], tick: int) -> None:
        for node in live:
            if not node.is_leader:
                continue
            term = node.current_term
            holder = self.leaders_by_term.get(term)
            if holder is None:
                self.leaders_by_term[term] = node.node_id
            elif holder != node.node_id:
                raise SafetyViolation(
                    ELECTION_SAFETY,
                    f"term {term} has two leaders: {holder} and {node.node_id}",
                    tick,
                )

    def check_commit_regression(self, live: list["Node"], tick: int) -> None:
        for node in live:
            previous = self.last_commit_index.get(node.node_id, 0)
            restarts = self.seen_restarts.get(node.node_id, 0)
            if node.restarts != restarts:
                # A restart legitimately resets the volatile commit index.
                self.seen_restarts[node.node_id] = node.restarts
                previous = 0
            if node.commit_index < previous:
                raise SafetyViolation(
                    COMMIT_REGRESSION,
                    f"{node.node_id} commit index went from {previous} to {node.commit_index} without a restart",
                    tick,
                )
            self.last_commit_index[node.node_id] = node.commit_index

    def record_commits(self, live: list["Node"], tick: int) -> None:
        """Remember every ``(index, term)`` any node considers committed. A
        second commit at the same index with a different term is a state
        machine safety violation in waiting, and is reported as such."""

        for node in live:
            for index in range(node.log.first_index, node.commit_index + 1):
                entry = node.log.at(index)
                known = self.committed.get(index)
                if known is None:
                    self.committed[index] = CommittedRecord(index, entry.term, entry.summary(), node.node_id, tick)
                elif known.term != entry.term or known.summary != entry.summary():
                    raise SafetyViolation(
                        STATE_MACHINE_SAFETY,
                        f"index {index} committed as {known.summary} (term {known.term}) by {known.by} at tick "
                        f"{known.tick} but {node.node_id} committed {entry.summary()} (term {entry.term})",
                        tick,
                    )

    def check_log_matching(self, live: list["Node"], tick: int) -> None:
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                self._check_pair(a, b, tick)

    @staticmethod
    def _check_pair(a: "Node", b: "Node", tick: int) -> None:
        low = max(a.log.first_index, b.log.first_index)
        high = min(a.log.last_index, b.log.last_index)
        if high < low:
            return
        # The highest index at which the two logs carry the same term.
        anchor = None
        for index in range(high, low - 1, -1):
            if a.log.at(index).term == b.log.at(index).term:
                anchor = index
                break
        if anchor is None:
            return
        for index in range(low, anchor):
            ea, eb = a.log.at(index), b.log.at(index)
            if ea.term != eb.term or ea.summary() != eb.summary():
                raise SafetyViolation(
                    LOG_MATCHING,
                    f"{a.node_id} and {b.node_id} agree at index {anchor} (term {a.log.at(anchor).term}) "
                    f"but differ at index {index}: {ea.summary()} vs {eb.summary()}",
                    tick,
                )

    def check_leader_completeness(self, live: list["Node"], tick: int) -> None:
        for node in live:
            if not node.is_leader:
                continue
            for index, record in self.committed.items():
                if record.term >= node.current_term:
                    continue
                if index < node.log.first_index:
                    continue  # compacted away; the snapshot carries it
                term = node.log.term_at(index)
                if term is None:
                    raise SafetyViolation(
                        LEADER_COMPLETENESS,
                        f"leader {node.node_id} (term {node.current_term}) lacks index {index}, "
                        f"committed in term {record.term} by {record.by} at tick {record.tick}",
                        tick,
                    )
                if term != record.term:
                    raise SafetyViolation(
                        LEADER_COMPLETENESS,
                        f"leader {node.node_id} (term {node.current_term}) holds term {term} at index {index}, "
                        f"which was committed with term {record.term} by {record.by} at tick {record.tick}",
                        tick,
                    )

    def check_state_machine_safety(self, live: list["Node"], tick: int) -> None:
        for node in live:
            for index in range(node.log.first_index, node.state_machine.last_applied + 1):
                entry = node.log.at(index)
                fact = (entry.term, entry.summary())
                known = self.applied.get(index)
                if known is None:
                    self.applied[index] = fact
                elif known != fact:
                    raise SafetyViolation(
                        STATE_MACHINE_SAFETY,
                        f"{node.node_id} applied {fact[1]} (term {fact[0]}) at index {index} "
                        f"but another node applied {known[1]} (term {known[0]})",
                        tick,
                    )
                record = self.committed.get(index)
                if record is not None and (record.term, record.summary) != fact:
                    raise SafetyViolation(
                        STATE_MACHINE_SAFETY,
                        f"{node.node_id} applied {fact[1]} (term {fact[0]}) at index {index} "
                        f"but {record.summary} (term {record.term}) was committed there",
                        tick,
                    )

    def check_membership_split(self, live: list["Node"], tick: int) -> None:
        configs: list[tuple[str, Configuration]] = [(n.node_id, n.config) for n in live]
        for i, (ida, a) in enumerate(configs):
            for idb, b in configs[i + 1:]:
                if a == b:
                    continue
                if disjoint_quorums_possible(a, b):
                    raise SafetyViolation(
                        MEMBERSHIP_SPLIT,
                        f"{ida} holds {a.describe()} and {idb} holds {b.describe()}; "
                        f"the two admit disjoint majorities",
                        tick,
                    )

    # -- reporting ---------------------------------------------------------

    def summary(self) -> dict:
        return {
            "checks": self.checks,
            "terms_with_leader": len(self.leaders_by_term),
            "leaders_by_term": dict(sorted(self.leaders_by_term.items())),
            "committed_indexes": len(self.committed),
            "highest_committed": max(self.committed) if self.committed else 0,
        }

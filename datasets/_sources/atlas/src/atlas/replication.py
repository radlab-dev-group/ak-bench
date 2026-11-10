"""Quorum replication over in-process replica nodes.

One :class:`Node` is one replica of the whole cluster: it owns a
:class:`~atlas.storage.ShardStorage` per shard. A write goes to the replicas
the current plan names, and succeeds when at least ``write_consistency`` of
them have it durably. A read touches ``read_consistency`` replicas and
resolves the answers. ``read + write > replication_factor`` is what makes a
read see a write, and the configuration enforces the inequality because
without it the store is not a quorum store and no amount of care in the read
path fixes that.

Replicas are objects in one process. There is no network, no thread and no
timer, which is deliberate: a divergence between two replicas must be
producible by calling methods in a fixed order, not by winning a race.

A replica has a lifecycle state besides "present": it may be **draining**,
which is the window between the operator's decision to retire it and the
rebalance that takes its keys away. The two helper functions at module level,
:func:`holders` and :func:`voters`, are the only place that window is
interpreted, and every path that needs "which replicas" asks one of them.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any

from .errors import QuorumShortfallError
from .fencing import FenceBook
from .registry import STRATEGIES
from .storage import ShardStorage
from .values import Record
from .vclock import VersionVector, compare


@dataclass
class Node:
    """One replica: every shard, backed by a directory."""

    node_id: str
    epoch: int
    root: pathlib.Path
    shard_count: int
    config: object = None
    stores: dict[int, ShardStorage] = field(default_factory=dict)
    #: Set while the replica is being retired: it still holds every key the
    #: plan gives it and still takes writes and repairs, but it is leaving.
    draining: bool = False

    def __post_init__(self) -> None:
        self.root = pathlib.Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        for shard in range(self.shard_count):
            self.stores[shard] = ShardStorage(
                self.root / f"shard-{shard}", shard, config=self.config
            )

    def store(self, shard: int) -> ShardStorage:
        return self.stores[shard]

    def drain(self) -> None:
        """Mark the replica as leaving. Nothing is moved here; the rebalance moves it."""

        self.draining = True

    def resume(self) -> None:
        self.draining = False

    def reopen(self) -> "Node":
        return Node(
            node_id=self.node_id,
            epoch=self.epoch,
            root=self.root,
            shard_count=self.shard_count,
            config=self.config,
            draining=self.draining,
        )

    def fingerprint(self) -> str:
        parts = []
        for shard in sorted(self.stores):
            data = self.stores[shard].state.stats()
            parts.append(f"{shard}:{data['keys']}:{data['last_lsn']}")
        return "|".join(parts)


def holders(nodes: dict[str, Node], names) -> list[str]:
    """Of ``names``, the replicas that hold the data: every present node, draining included.

    This is the set a write lands on, a repair writes forward to, and a
    rebalance streams from. A draining replica is in it until the plan stops
    naming it, because the bytes are there and nowhere else yet.
    """

    return [name for name in names if name in nodes]


def voters(nodes: dict[str, Node], names) -> list[str]:
    """Of ``names``, the replicas whose acknowledgment counts toward a quorum.

    A draining replica holds the data and does not vote: its acknowledgment is
    a promise made by a node that is leaving, and a quorum built on it is one
    the read side cannot find again after the rebalance.
    """

    return [name for name in names if name in nodes and not nodes[name].draining]


class Replicator:
    """Drives a write or a read across the replicas the plan names.

    The plan answers *which replica*, and the hash answers *which shard*; the
    two are different questions and a store address needs both. ``shard_of`` is
    injected because the shard function belongs to the store, not to placement.
    """

    def __init__(
        self,
        nodes: dict[str, Node],
        *,
        config,
        shard_of,
        conflict: str | None = None,
    ) -> None:
        self.nodes = nodes
        self.config = config
        self.shard_of = shard_of
        self.conflict_name = conflict or config["tie_break"]
        self.resolve_conflict = STRATEGIES.resolve_conflict(self.conflict_name)

    def targets(self, key: str, placement) -> list[str]:
        count = int(self.config["replication_factor"])
        return list(placement.replicas_for(key, count))

    def write(
        self,
        key: str,
        value: Any,
        *,
        placement,
        writer: str,
        expected_generation: int | None = None,
        attributes: dict[str, str] | None = None,
    ) -> Record:
        """Write to ``W`` replicas. Partial success is a failure, not a retry hint."""

        replicas = self.targets(key, placement)
        needed = int(self.config["write_consistency"])
        voting = set(voters(self.nodes, replicas))
        acknowledged: list[Record] = []
        written: list[str] = []
        failures: list[str] = []
        for replica in replicas:
            node = self.nodes.get(replica)
            if node is None:
                failures.append(f"{replica}: no such node")
                continue
            try:
                acknowledged.append(
                    node.store(self.shard_of(key)).put(
                        key,
                        value,
                        writer=writer,
                        expected_generation=expected_generation,
                        attributes=attributes,
                    )
                )
                written.append(replica)
            except Exception as exc:  # noqa: BLE001 - a replica failure is data
                failures.append(f"{replica}: {exc}")
        votes = [replica for replica in written if replica in voting]
        if len(votes) < needed:
            raise QuorumShortfallError(
                key, placement.epoch(), len(votes), needed, phase="write", failures=failures
            )
        return acknowledged[0]

    def read(self, key: str, *, placement, repair=None) -> tuple[Record | None, list[Record]]:
        """Read ``R`` replicas and resolve.

        The second element is every answer that came back, including the ones
        that lost, which is what a repair decision and a witness assertion
        both need.
        """

        replicas = self.targets(key, placement)
        needed = int(self.config["read_consistency"])
        voting = set(voters(self.nodes, replicas))
        answers: list[Record] = []
        failures: list[str] = []
        answered = 0
        for replica in replicas:
            node = self.nodes.get(replica)
            if node is None:
                failures.append(f"{replica}: no such node")
                continue
            # A replica that answers "no such key" has answered: an absent key
            # is an answer, not a failure, and treating it as one makes the
            # first read of a new key a quorum error. A draining replica's
            # answer is taken into the resolution but does not count toward
            # the read quorum, for the same reason its write does not.
            if replica in voting:
                answered += 1
            record = node.store(self.shard_of(key)).resolve(key)
            if record is not None:
                answers.append(record)
        if answered < needed:
            raise QuorumShortfallError(
                key, placement.epoch(), answered, needed, phase="read", failures=failures
            )
        if not answers:
            return None, []
        candidates = [(record.vector, record) for record in answers]
        _vector, winner = self.resolve_conflict(
            candidates, equal_is_conflict=False
        )
        if repair is not None and len({record.generation for record in answers}) > 1:
            repair.repair(key, winner, replicas=replicas, placement=placement)
        return winner, answers

    def quorum_sizes(self) -> dict[str, int]:
        return {
            "replication_factor": int(self.config["replication_factor"]),
            "write_consistency": int(self.config["write_consistency"]),
            "read_consistency": int(self.config["read_consistency"]),
        }

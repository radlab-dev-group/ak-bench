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
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any

from .errors import QuorumError
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
    config=None
    stores: dict[int, ShardStorage] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = pathlib.Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        for shard in range(self.shard_count):
            self.stores[shard] = ShardStorage(
                self.root / f"shard-{shard}", shard, config=self.config
            )

    def store(self, shard: int) -> ShardStorage:
        return self.stores[shard]

    def reopen(self) -> "Node":
        return Node(
            node_id=self.node_id,
            epoch=self.epoch,
            root=self.root,
            shard_count=self.shard_count,
            config=self.config,
        )

    def fingerprint(self) -> str:
        parts = []
        for shard in sorted(self.stores):
            data = self.stores[shard].state.stats()
            parts.append(f"{shard}:{data['keys']}:{data['last_lsn']}")
        return "|".join(parts)


class Replicator:
    """Drives a write or a read across the replicas the plan names."""

    def __init__(self, nodes: dict[str, Node], *, config, conflict: str | None = None) -> None:
        self.nodes = nodes
        self.config = config
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
        acknowledged: list[Record] = []
        failures: list[str] = []
        for replica in replicas:
            node = self.nodes.get(replica)
            if node is None:
                failures.append(f"{replica}: no such node")
                continue
            try:
                acknowledged.append(
                    node.store(placement.owner(key)).put(
                        key,
                        value,
                        writer=writer,
                        expected_generation=expected_generation,
                        attributes=attributes,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - a replica failure is data
                failures.append(f"{replica}: {exc}")
        if len(acknowledged) < needed:
            raise QuorumError(
                f"write of {key!r} reached {len(acknowledged)} of {needed} required replicas; "
                f"failures: {failures}"
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
        answers: list[Record] = []
        failures: list[str] = []
        for replica in replicas:
            node = self.nodes.get(replica)
            if node is None:
                failures.append(f"{replica}: no such node")
                continue
            record = node.store(placement.owner(key)).resolve(key)
            if record is not None:
                answers.append(record)
        if len(answers) + len(failures) < needed:
            raise QuorumError(
                f"read of {key!r} reached {len(answers)} answering replicas of {needed} required"
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

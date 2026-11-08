"""The Atlas store: the API callers use and the place every subsystem meets.

One :class:`Atlas` object is one cluster: a membership, a placement service,
one :class:`~atlas.replication.Node` per replica, and the write and read paths
that go through them.

The write path, in order, with the check each step owns:

1. ``shard_of(key)``          — which partition unit holds the key;
2. ``placement.owner(key)``   — which replica is primary, **from the current plan**;
3. ``fence.check_write``      — the epoch the write was planned under, then the generation;
4. ``storage.put``            — the log append, then the memtable;
5. ``quorum arithmetic``      — enough replicas, or the write did not happen;
6. ``lineage.record_write``   — the derived edge, if lineage is enabled.

Step 2 has one rule and it is worth stating because a rebalance is the moment
it matters: **the owner is asked of the current plan, at the moment of the
write**. A plan held across a publication is a stale answer, and a stale
answer does not fail, it writes to a replica that no longer holds the key.
The same is true of the shard function: it depends on nothing but the key and
the shard count, so it is stable across a rebalance while the *owner* is not.

The read path resolves whatever the replicas report, and repairs when they
disagree; :mod:`atlas.repair` owns the winner rule and this module only asks
for it, so there is exactly one implementation of "which version wins".
"""

from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Config, build as build_config
from .errors import KeyNotFoundError, StaleGenerationError
from .fencing import FenceBook
from .faults import CrashPlan, NO_CRASH
from .membership import Membership
from .placement import Plan, PlacementService
from .rebalance import Rebalancer
from .repair import ReadRepairer
from .replication import Node, Replicator
from .transaction import Transaction
from .values import Record

#: The number of replicas a key is written to when the configuration does not
#: say. It is a default, not a constant; ``replication_factor`` wins.
DEFAULT_REPLICAS = ("atlas-0", "atlas-1", "atlas-2")


def hash_shard(key: str, shard_count: int) -> int:
    """The shard function: a pure function of the key and the shard count.

    It deliberately does not consult placement, a plan or membership, because
    a key's *partition* must not move when its *owner* does. Mixing the two
    is how a rebalance ends up writing a key into two partitions.
    """

    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % shard_count


@dataclass
class WriteResult:
    key: str
    record: Record
    replicas: tuple[str, ...]
    acknowledged: int
    fenced: bool = False


class Atlas:
    """A cluster of replicas behind one API."""

    def __init__(
        self,
        *,
        config: Config,
        root: pathlib.Path | str,
        replicas=None,
        crash: CrashPlan | None = None,
        epoch: int | None = None,
    ) -> None:
        self.config = config
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.crash = crash or NO_CRASH
        self.epoch = int(epoch if epoch is not None else config["epoch"])
        names = tuple(replicas or DEFAULT_REPLICAS[: int(config["replication_factor"])])
        self.membership = Membership(self.epoch)
        self.nodes: dict[str, Node] = {}
        for name in names:
            self.membership.add(name)
            self.nodes[name] = Node(
                node_id=name,
                epoch=self.epoch,
                root=self.root / name,
                shard_count=int(config["shards"]),
                config=config,
            )
        self.placement = PlacementService(
            self.epoch, names, vnodes=int(config["vnodes"])
        )
        self.fence = FenceBook(self.membership, generation_check=config["generation_check"])
        self.replicator = Replicator(self.nodes, config=config, shard_of=self.shard_of)
        self.repairer = ReadRepairer(self.nodes, config=config, shard_of=self.shard_of)
        self.rebalancer = Rebalancer(
            self.nodes, placement=self.placement, config=self.config, shard_of=self.shard_of
        )
        self._lineage = None

    # --------------------------------------------------------------- routing
    def shard_of(self, key: str) -> int:
        return hash_shard(key, int(self.config["shards"]))

    def owner(self, key: str) -> str:
        """The current primary of ``key``. Always the current plan, always now."""

        return self.placement.owner(key)

    def replicas_for(self, key: str):
        return self.replicator.targets(key, self.placement)

    # ------------------------------------------------------------------ write
    def put(
        self,
        key: str,
        value: Any,
        *,
        writer: str | None = None,
        expected_generation: int | None = None,
        attributes: dict[str, str] | None = None,
    ) -> WriteResult:
        author = writer or str(self.config["node_id"])
        planned_epoch = self.placement.epoch()
        self.fence.check_write(
            key,
            writer=author,
            offered_generation=(
                expected_generation
                if expected_generation is not None
                else self.current_generation(key)
            ),
            planned_epoch=planned_epoch,
        )
        record = self.replicator.write(
            key,
            value,
            placement=self.placement,
            writer=author,
            expected_generation=expected_generation,
            attributes=attributes,
        )
        replicas = self.replicas_for(key)
        self.fence.advance_lease(key, author, record.generation)
        result = WriteResult(
            key=key,
            record=record,
            replicas=tuple(replicas),
            acknowledged=len(replicas),
        )
        self._record_lineage(key, record, author=author, cause=None)
        return result

    def delete(self, key: str, *, writer: str | None = None, expected_generation: int | None = None) -> WriteResult:
        author = writer or str(self.config["node_id"])
        current = self.resolve(key)
        if current is None:
            raise KeyNotFoundError(key)
        planned_epoch = self.placement.epoch()
        self.fence.check_write(
            key,
            writer=author,
            offered_generation=current.generation if expected_generation is None else expected_generation,
            planned_epoch=planned_epoch,
        )
        replicas = self.replicas_for(key)
        shard = self.shard_of(key)
        record = None
        failures: list[str] = []
        acknowledged = 0
        for replica in replicas:
            try:
                made = self.nodes[replica].store(shard).delete(
                    key, writer=author, expected_generation=expected_generation
                )
                record = made if record is None else record
                acknowledged += 1
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{replica}: {exc}")
        if record is None or acknowledged < int(self.config["write_consistency"]):
            from .errors import QuorumError

            raise QuorumError(f"delete of {key!r} acknowledged by {acknowledged}: {failures}")
        self.fence.advance_lease(key, author, record.generation)
        self._record_lineage(key, record, author=author, cause=None)
        return WriteResult(key=key, record=record, replicas=tuple(replicas), acknowledged=acknowledged)

    def acknowledge(self, key: str, offered_generation: int, *, writer: str | None = None) -> int:
        """A commit marker for a write the caller already made.

        The acknowledgment carries the generation the caller believes it
        committed at. It is checked the same way a write is: an offer for a
        generation that is no longer current is refused, because acknowledging
        work a replacement has since redone is how a system double-applies it.
        """

        author = writer or str(self.config["node_id"])
        self.fence.acknowledge(
            key,
            offered_generation,
            self.placement.epoch(),
            author,
        )
        return offered_generation

    # ------------------------------------------------------------------- read
    def get(self, key: str) -> Record | None:
        record, _answers = self.replicator.read(key, placement=self.placement, repair=self.repairer)
        if record is None or record.deleted:
            # A tombstone is durable state, not an answer to a read: it exists
            # so that a delete survives a replay, and :meth:`resolve` is the
            # way to see it.
            return None
        return record

    def resolve(self, key: str) -> Record | None:
        """The winning record, tombstone included, without triggering repair."""

        record, _answers = self.replicator.read(key, placement=self.placement, repair=None)
        return record

    def read_replicas(self, key: str) -> list[Record]:
        """What each replica actually says, in replica order."""

        shard = self.shard_of(key)
        found: list[Record] = []
        for replica in self.replicas_for(key):
            record = self.nodes[replica].store(shard).resolve(key)
            if record is not None:
                found.append(record)
        return found

    def current_generation(self, key: str) -> int:
        record = self.resolve(key)
        return record.generation if record is not None else 0

    def generation_at(self, key: str) -> int:
        """The generation the fencing book holds, which may differ from storage.

        The fence is the admission control; storage is what was durably
        written. They agree on a healthy node and diverge exactly when a write
        was refused, which is the case a witness test reads.
        """

        return self.fence.current_generation(key)

    # ----------------------------------------------------------- transactions
    def transaction(self, writer: str | None = None) -> Transaction:
        author = writer or str(self.config["node_id"])
        return Transaction(
            writer=author,
            fence=self.fence,
            planned_epoch=self.placement.epoch(),
        )

    def commit_transaction(self, transaction: Transaction) -> list[tuple[str, Any]]:
        writes = transaction.commit(generations_now=lambda key: self.current_generation(key))
        results: list[tuple[str, Any]] = []
        for key, value in writes:
            result = self.put(key, value, writer=transaction.writer)
            results.append((key, result.record.value))
        return results

    # -------------------------------------------------------------- durability
    def compact(self, shard: int | None = None) -> dict[str, Any]:
        """Snapshot every shard of every replica; return the per-shard summary."""

        targets = range(int(self.config["shards"])) if shard is None else [int(shard)]
        summary: dict[str, Any] = {}
        for replica in sorted(self.nodes):
            for index in targets:
                snapshot = self.nodes[replica].store(index).snapshot()
                summary[f"{replica}/{index}"] = {
                    "last_lsn": snapshot.last_lsn,
                    "keys": snapshot.key_count,
                    "tombstones": snapshot.tombstones,
                    "published": snapshot.published,
                }
        return summary

    def recover(self) -> dict[str, Any]:
        """Reopen every replica from disk, as a process restart would."""

        report: dict[str, Any] = {"replicas": {}, "replayed": 0, "skipped": 0, "torn": False}
        for name in sorted(self.nodes):
            node = self.nodes[name]
            reopened = node.reopen()
            for index, store in reopened.stores.items():
                report["replicas"][f"{name}/{index}"] = store.recovery.as_dict()
                report["replayed"] += store.recovery.replayed
                report["skipped"] += store.recovery.skipped
                report["torn"] = report["torn"] or store.recovery.torn
            self.nodes[name] = reopened
        return report

    def reopen_replica(self, name: str) -> Node:
        node = self.nodes[name].reopen()
        self.nodes[name] = node
        self.replicator.nodes = self.nodes
        self.repairer.nodes = self.nodes
        self.rebalancer.nodes = self.nodes
        return node

    # --------------------------------------------------------------- rebalance
    def rebalance(self, replicas) -> Any:
        keys = self.stored_keys()
        for name in replicas:
            if name not in self.nodes:
                self.membership.add(name)
                self.nodes[name] = Node(
                    node_id=name,
                    epoch=self.placement.epoch(),
                    root=self.root / name,
                    shard_count=int(self.config["shards"]),
                    config=self.config,
                )
        self.replicator.nodes = self.nodes
        self.repairer.nodes = self.nodes
        self.rebalancer.nodes = self.nodes
        report = self.rebalancer.run(
            replicas, state_keys=keys, epoch=self.placement.epoch() + 1
        )
        # A node that leaves is kept until after the source has been released,
        # because the release is a write; the membership moves on only after.
        self.membership = self.membership.advance()
        self.fence.membership = self.membership
        self.epoch = self.placement.epoch()
        return report

    def stored_keys(self) -> list[str]:
        found: set[str] = set()
        for node in self.nodes.values():
            for store in node.stores.values():
                found.update(store.state.keys())
        return sorted(found)

    def lineage(self):
        """The lineage recorder, or ``None`` when the feature is not enabled."""

        return self._lineage

    def enable_lineage(self, recorder) -> None:
        self._lineage = recorder

    def _record_lineage(self, key: str, record: Record, *, author: str, cause) -> None:
        if self._lineage is None or not bool(self.config.get("lineage_enabled", True)):
            return
        self._lineage.record_write(key, record, author=author, cause=cause)

    def stats(self) -> dict[str, Any]:
        return {
            "epoch": self.placement.epoch(),
            "plan": self.placement.fingerprint(),
            "nodes": sorted(self.nodes),
            "quorum": self.replicator.quorum_sizes(),
            "shards": int(self.config["shards"]),
            "keys": len(self.stored_keys()),
        }


class AtlasBuilder:
    """Assemble a cluster; every setter returns the builder."""

    def __init__(self) -> None:
        self._config_values: dict[str, Any] = {}
        self._root: pathlib.Path | str = "./atlas-data"
        self._replicas: tuple[str, ...] | None = None
        self._crash: CrashPlan = NO_CRASH
        self._epoch: int | None = None
        self._config: Config | None = None

    def config(self, config: Config) -> "AtlasBuilder":
        self._config = config
        return self

    def set(self, key: str, value: Any) -> "AtlasBuilder":
        self._config_values[key] = value
        return self

    def root(self, path: pathlib.Path | str) -> "AtlasBuilder":
        self._root = path
        return self

    def replicas(self, *names: str) -> "AtlasBuilder":
        self._replicas = tuple(names)
        return self

    def crash(self, plan: CrashPlan) -> "AtlasBuilder":
        self._crash = plan
        return self

    def epoch(self, epoch: int) -> "AtlasBuilder":
        self._epoch = int(epoch)
        return self

    def build(self) -> Atlas:
        config = self._config or build_config(values=self._config_values, path="none.toml", env={})
        replicas = self._replicas
        if replicas is None:
            replicas = DEFAULT_REPLICAS[: int(config["replication_factor"])]
        return Atlas(
            config=config,
            root=self._root,
            replicas=replicas,
            crash=self._crash,
            epoch=self._epoch,
        )

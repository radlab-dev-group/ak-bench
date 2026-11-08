"""Read repair and the reconciliation of divergent replicas.

Two replicas of one key disagree because a write reached some of them and not
others, or because a node was cut off, kept serving reads, and came back.
Repair is what makes the cluster converge, and it has one rule that decides
almost everything: **the winner is the version that dominates causally, and
when neither dominates, the documented tie-break decides**. In this store the
tie-break is *descending writer identifier* under the default configuration.
It is not an arbitrary choice that could be flipped without consequence —
every replica must pick the same winner or repair makes the cluster
permanently divergent, and the tie-break is the only thing synchronising them.

Repair writes the winner forward. It never writes a loser, and it never
invents a merged value: a concurrent update to a map is still one winner and
one discarded write, because silently merging is how a store loses data while
reporting success.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import ReadRepairConflictError
from .registry import STRATEGIES
from .values import Record
from .vclock import VersionVector, compare, tie_break_key


@dataclass
class RepairOutcome:
    key: str
    winner: Record | None
    losers: tuple[Record, ...] = ()
    written_to: tuple[str, ...] = ()
    #: True when the winner was chosen by the tie-break rather than by causal
    #: dominance. A repair that needs the tie-break on every read is a cluster
    #: that is writing concurrently, which is a different problem from repair.
    by_tie_break: bool = False
    notes: list[str] = field(default_factory=list)


class ReadRepairer:
    def __init__(self, nodes, *, config, shard_of, conflict: str | None = None) -> None:
        self.nodes = nodes
        self.config = config
        self.shard_of = shard_of
        self.conflict_name = conflict or config["tie_break"]
        self.resolve = STRATEGIES.resolve_conflict(self.conflict_name)

    def choose(self, candidates) -> tuple[Record, tuple[Record, ...], bool]:
        """Pick the winner among records, and report whether the tie-break decided.

        ``candidates`` are records for one key as reported by different
        replicas. A record that dominates all others wins; a strict tie
        between equal vectors is a conflict, not a winner; two concurrent
        vectors are settled by the tie-break.
        """

        if not candidates:
            raise ReadRepairConflictError("<none>", None, None)
        ordered = sorted(candidates, key=lambda record: record.vector, reverse=True)
        best = ordered[0]
        losers: list[Record] = []
        by_tie_break = False
        for record in ordered[1:]:
            relation = compare(record.vector, best.vector)
            if relation == 2:
                by_tie_break = True
                if tie_break_key(record.vector) > tie_break_key(best.vector):
                    losers.append(best)
                    best = record
                else:
                    losers.append(record)
            elif relation == 0:
                if record.generation != best.generation:
                    losers.append(record)
                elif record.lsn != best.lsn:
                    raise ReadRepairConflictError(record.key, best.render(), record.render())
                else:
                    losers.append(record)
            else:
                losers.append(record)
        return best, tuple(losers), by_tie_break

    def repair(self, key: str, winner: Record, *, replicas, placement) -> RepairOutcome:
        """Write ``winner`` to every replica that does not already have it."""

        written: list[str] = []
        for replica in replicas:
            node = self.nodes.get(replica)
            if node is None:
                continue
            store = node.store(self.shard_of(key))
            current = store.resolve(key)
            if current is not None and current.vector == winner.vector and current.generation == winner.generation:
                continue
            store.apply_records([winner], reconcile=True)
            written.append(replica)
        return RepairOutcome(key=key, winner=winner, written_to=tuple(written))

    def reconcile(self, key: str, candidates, *, replicas=None, placement=None) -> RepairOutcome:
        """Resolve a set of reported versions and, when asked, write the winner forward."""

        winner, losers, by_tie_break = self.choose(candidates)
        outcome = self.repair(key, winner, replicas=replicas or [], placement=placement) if replicas else RepairOutcome(
            key=key, winner=winner, losers=losers, by_tie_break=by_tie_break
        )
        return RepairOutcome(
            key=key,
            winner=winner,
            losers=losers,
            written_to=outcome.written_to,
            by_tie_break=by_tie_break,
            notes=outcome.notes,
        )

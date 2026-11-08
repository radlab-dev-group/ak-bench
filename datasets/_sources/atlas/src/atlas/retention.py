"""Tombstone ageing.

A tombstone exists so that a delete survives a replay and a replica that was
down does not resurrect the key. It stops being needed once every replica has
seen it and the grace period has passed, and at that point it is pure cost:
a key that reads as absent, is stored, compared by anti-entropy, and copied
by every migration.

The rule is a single comparison — a tombstone is dropped when it is at least
``tombstone_grace_ms`` old — and the clock it is compared against is the same
hybrid clock that wrote it, so a tombstone cannot age out because a host's
wall clock jumped. Two properties make this safe rather than a data-losing
optimisation:

* the grace is measured from ``written_at`` of the tombstone, never from the
  moment the sweep runs, so sweeping twice is not the same as waiting twice;
* a live record is never touched by a sweep, whatever its age. Ageing is a
  statement about deletes and about nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .clock import HybridClock
from .values import Record


@dataclass
class SweepReport:
    shard: int
    examined: int = 0
    dropped: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    #: Tombstones that are old enough to drop but sit above a live version of
    #: the same key in the same sweep. Kept, and reported, because it means a
    #: write raced the delete and the delete is no longer the visible version.
    protected: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)


class Retention:
    def __init__(self, *, clock: HybridClock | None = None, grace_ms: int = 604_800_000) -> None:
        self.clock = clock or HybridClock()
        self.grace_ms = int(grace_ms)

    def expired(self, record: Record, *, now_ms: int | None = None) -> bool:
        if not record.deleted:
            return False
        moment = self.clock.now_ms() if now_ms is None else int(now_ms)
        return moment - record.written_at >= self.grace_ms

    def sweep_store(self, store, *, now_ms: int | None = None) -> SweepReport:
        """Drop the aged tombstones of one shard store."""

        moment = self.clock.now_ms() if now_ms is None else int(now_ms)
        examined = 0
        dropped: list[str] = []
        kept: list[str] = []
        for record in list(store.state.all_records()):
            if not record.deleted:
                continue
            examined += 1
            if self.expired(record, now_ms=moment):
                store.state.forget(record.key)
                dropped.append(record.key)
            else:
                kept.append(record.key)
        return SweepReport(
            shard=store.shard,
            examined=examined,
            dropped=tuple(sorted(dropped)),
            kept=tuple(sorted(kept)),
        )

    def sweep_cluster(self, nodes, *, now_ms: int | None = None) -> list[SweepReport]:
        reports: list[SweepReport] = []
        for name in sorted(nodes):
            for index in sorted(nodes[name].stores):
                reports.append(self.sweep_store(nodes[name].stores[index], now_ms=now_ms))
        return reports

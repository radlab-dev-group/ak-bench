"""The in-memory state of one shard: keys, generations and tombstones.

The memtable is the answer to "what does this replica believe right now". It
is deliberately boring: a dictionary of key to :class:`~atlas.values.Record`
plus the highest LSN it has absorbed. Everything interesting about durability
lives in the WAL and the snapshot; everything interesting about agreement
lives in replication and repair.

Two invariants the rest of the store relies on:

* **generations are monotonic per key**. :meth:`Memtable.apply` refuses a
  record whose generation is not greater than the stored one, unless the
  caller is explicitly reconciling replicas (``reconcile=True``), where a
  higher *vector* may replace a lower generation;
* **a tombstone is a value**. It occupies the key, carries a generation, and
  only :meth:`purge` removes it, and only after the grace period.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator

from .errors import StaleGenerationError
from .values import Record
from .vclock import VersionVector, compare

BEFORE = -1
AFTER = 1


@dataclass
class Memtable:
    shard: int
    records: dict[str, Record] = field(default_factory=dict)
    last_lsn: int = 0
    #: Counts every write applied since the last snapshot, which is the
    #: trigger compaction reads.
    writes_since_snapshot: int = 0

    def __len__(self) -> int:
        return len(self.records)

    def __contains__(self, key: str) -> bool:
        record = self.records.get(key)
        return record is not None and not record.deleted

    def get(self, key: str) -> Record | None:
        return self.records.get(key)

    def live(self) -> Iterator[Record]:
        for record in sorted(self.records.values(), key=lambda item: item.key):
            if not record.deleted:
                yield record

    def all_records(self) -> Iterator[Record]:
        for record in sorted(self.records.values(), key=lambda item: item.key):
            yield record

    def keys(self) -> list[str]:
        return sorted(self.records)

    def generation(self, key: str) -> int:
        record = self.records.get(key)
        return record.generation if record is not None else 0

    def next_generation(self, key: str) -> int:
        return self.generation(key) + 1

    def apply(self, record: Record, *, reconcile: bool = False) -> Record:
        """Store ``record``, enforcing the per-key generation order.

        With ``reconcile`` the caller is merging replica state and the winner
        is chosen by the version vector instead of by generation; that is how
        read repair writes a peer's version forward without tripping fencing.
        """

        current = self.records.get(record.key)
        if current is None:
            self.records[record.key] = record
            self._absorb(record)
            return record
        if reconcile:
            relation = compare(record.vector, current.vector)
            if relation == BEFORE:
                return current
            if relation == 0 and record.generation <= current.generation:
                return current
        else:
            if record.generation <= current.generation and record.generation != current.generation:
                raise StaleGenerationError(record.key, record.generation, current.generation)
            if record.generation == current.generation and record.vector != current.vector:
                raise StaleGenerationError(record.key, record.generation, current.generation)
        self.records[record.key] = record
        self._absorb(record)
        return record

    def _absorb(self, record: Record) -> None:
        if record.lsn > self.last_lsn:
            self.last_lsn = record.lsn
        self.writes_since_snapshot += 1

    def forget(self, key: str) -> None:
        self.records.pop(key, None)

    def purge(self, *, now_ms: int, grace_ms: int) -> list[str]:
        """Drop tombstones older than the grace period; return the keys dropped."""

        dropped: list[str] = []
        for key, record in list(self.records.items()):
            if (
                record.deleted
                and now_ms - record.written_at >= grace_ms
            ):
                self.records.pop(key, None)
                dropped.append(key)
        return sorted(dropped)

    def snapshot_records(self) -> list[Record]:
        """Everything the snapshot must carry, tombstones included."""

        return list(self.all_records())

    def restore(self, records: Iterable[Record], *, last_lsn: int) -> None:
        self.records = {record.key: record for record in records}
        self.last_lsn = int(last_lsn)
        self.writes_since_snapshot = 0

    def digest_records(self) -> list[Record]:
        return self.snapshot_records()

    def stats(self) -> dict[str, int]:
        tombstones = sum(1 for record in self.records.values() if record.deleted)
        return {
            "keys": len(self.records),
            "live": len(self.records) - tombstones,
            "tombstones": tombstones,
            "last_lsn": self.last_lsn,
            "writes_since_snapshot": self.writes_since_snapshot,
        }


def empty_vector() -> VersionVector:
    return VersionVector.new()

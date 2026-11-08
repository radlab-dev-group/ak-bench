"""Shard storage: memtable plus log plus snapshot, and the recovery that joins them.

Recovery is the whole point of this module. A shard opens by reading the
published snapshot, restoring the memtable to it, and then applying the log
**strictly after** the snapshot's LSN. The order matters twice over:

1. reading CURRENT before touching the log, so that a snapshot published
   between two opens is honoured;
2. applying log records after the snapshot in log order, so that a key written
   before and after the snapshot ends at its later value.

Re-applying a record the snapshot already contains is not harmless here. The
counters a witness test asserts on are plain integers kept in the value, so a
double-applied increment is a wrong answer that no checksum catches. The
boundary convention in :mod:`atlas.clock` is what keeps the two halves of the
log from overlapping, and it is configured, not hardcoded, precisely so it can
be stated once and obeyed everywhere.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any

from .clock import LSNBounds, MonotonicCounter
from .codec import FrameKind
from .errors import KeyNotFoundError, StaleGenerationError
from .faults import CrashPlan, NO_CRASH
from .memtable import Memtable
from .snapshot import Snapshot, SnapshotStore
from .values import Record
from .vclock import VersionVector
from .wal import Transaction, WriteAheadLog, record_from_payload


@dataclass
class RecoveryReport:
    """What opening a shard found."""

    snapshot_lsn: int = 0
    replayed: int = 0
    skipped: int = 0
    transactions: int = 0
    truncated_bytes: int = 0
    torn: bool = False
    snapshot_published: bool = False
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_lsn": self.snapshot_lsn,
            "replayed": self.replayed,
            "skipped": self.skipped,
            "transactions": self.transactions,
            "truncated_bytes": self.truncated_bytes,
            "torn": self.torn,
            "snapshot_published": self.snapshot_published,
            "warnings": list(self.warnings),
        }


class ShardStorage:
    """One shard of one replica."""

    def __init__(
        self,
        directory: pathlib.Path | str,
        shard: int,
        *,
        config=None,
        crash: CrashPlan | None = None,
    ) -> None:
        self.root = pathlib.Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.shard = int(shard)
        self.config = config
        self.crash = crash or NO_CRASH
        fsync = True if config is None else bool(config["fsync_on_commit"])
        self.log = WriteAheadLog(
            self.root / "wal",
            fsync=fsync,
            max_bytes=8 * 1024 * 1024 if config is None else int(config["max_wal_bytes"]),
            repair_on_open=bool(True if config is None else config["torn_tail_repair"]),
        )
        self.snapshots = SnapshotStore(self.root / "snapshots", fsync=fsync)
        self.state = Memtable(shard=self.shard)
        self.bounds = LSNBounds() if config is None else LSNBounds.from_config(config)
        self.counter = MonotonicCounter(0)
        self.recovery = RecoveryReport()
        self.closed = False
        self._open()

    # --------------------------------------------------------------- recovery
    def _open(self) -> None:
        self.crash.hit("before_replay")
        snapshot = self.snapshots.load_current()
        if snapshot is not None:
            self.state.restore(snapshot.records, last_lsn=snapshot.last_lsn)
            self.recovery.snapshot_lsn = snapshot.last_lsn
            self.recovery.snapshot_published = snapshot.published
            self.counter.advance_to(snapshot.last_lsn)
        replayed: list[tuple[FrameKind, Record]] = []
        for kind, record in self.log.replay(bounds=self.bounds, snapshot_lsn=self.recovery.snapshot_lsn):
            replayed.append((kind, record))
        for _kind, record in replayed:
            self.state.apply(record, reconcile=True)
        self.recovery.replayed = len(replayed)
        self.recovery.skipped = self.log.report.skipped
        self.recovery.transactions = self.log.report.transactions
        self.recovery.truncated_bytes = self.log.report.truncated_bytes
        self.recovery.torn = self.log.report.torn
        self.recovery.warnings.extend(self.log.report.warnings)
        self.counter.advance_to(max(self.state.last_lsn, self.recovery.snapshot_lsn))
        self.crash.hit("after_replay")

    def reopen(self) -> "ShardStorage":
        """Close and open again, as a fresh process would.

        The in-memory half is dropped and rebuilt from disk. Anything a caller
        can observe after a reopen is therefore durable state, which is the
        only kind of state a crash scenario can assert on.
        """

        self.close()
        return ShardStorage(self.root, self.shard, config=self.config, crash=self.crash)

    def close(self) -> None:
        self.closed = True

    # ------------------------------------------------------------------ write
    def next_lsn(self) -> int:
        return self.counter.next()

    def put(
        self,
        key: str,
        value: Any,
        *,
        writer: str = "local",
        expected_generation: int | None = None,
        attributes: dict[str, str] | None = None,
        lsn: int | None = None,
    ) -> Record:
        current = self.state.get(key)
        if expected_generation is not None:
            observed = current.generation if current is not None else 0
            if observed != expected_generation:
                raise StaleGenerationError(key, expected_generation, observed)
        generation = self.state.next_generation(key)
        assigned = self.next_lsn() if lsn is None else int(lsn)
        if current is None:
            record = Record.put(
                key,
                value,
                generation=generation,
                writer=writer,
                lsn=assigned,
                attributes=attributes,
            )
        else:
            record = current.advance(
                value,
                writer=writer,
                lsn=assigned,
                attributes=attributes,
            )
        self._persist((record,))
        return record

    def delete(
        self,
        key: str,
        *,
        writer: str = "local",
        expected_generation: int | None = None,
        lsn: int | None = None,
    ) -> Record:
        current = self.state.get(key)
        if current is None or current.deleted:
            raise KeyNotFoundError(key)
        if expected_generation is not None and current.generation != expected_generation:
            raise StaleGenerationError(key, expected_generation, current.generation)
        assigned = self.next_lsn() if lsn is None else int(lsn)
        record = current.advance(
            None, writer=writer, lsn=assigned, deleted=True
        )
        self._persist((record,), delete=True)
        return record

    def apply_records(self, records, *, reconcile: bool = False) -> None:
        """Append already-built records as one transaction (replication, repair, migration)."""

        self._persist(tuple(records), reconcile=reconcile)

    def _persist(self, records, *, delete: bool = False, reconcile: bool = False) -> None:
        self.crash.hit("before_append")
        if not records:
            return
        first = records[0].lsn
        transaction = Transaction(txn_id=f"txn-{first}", lsn=first)
        for record in records:
            if record.deleted:
                transaction.delete(record)
            else:
                transaction.put(record)
        self.crash.hit("mid_frame")
        self.log.append(transaction)
        self.crash.hit("after_append")
        for record in records:
            self.state.apply(record, reconcile=reconcile)
        self.crash.hit("after_commit")

    # ------------------------------------------------------------------- read
    def get(self, key: str) -> Record | None:
        record = self.state.get(key)
        if record is None or record.deleted:
            return None
        return record

    def resolve(self, key: str) -> Record | None:
        """The raw stored record, tombstone included."""

        return self.state.get(key)

    def generation(self, key: str) -> int:
        return self.state.generation(key)

    def snapshot(self, *, publish: bool = True) -> Snapshot:
        """Compact: write the memtable as a snapshot and publish it.

        Publishing is the moment the log stops being authoritative for the
        records the snapshot carries, so the crash points around it are named
        for the decision: ``before_snapshot``, ``after_snapshot``,
        ``release_current``, ``after_release``.
        """

        self.crash.hit("before_snapshot")
        last_lsn = max(self.state.last_lsn, self.counter.value)
        written = self.snapshots.write(
            self.shard,
            self.state.snapshot_records(),
            last_lsn=last_lsn,
            publish=False,
        )
        self.crash.hit("after_snapshot")
        self.crash.hit("release_current")
        self.snapshots._publish(written.path.name)
        self.crash.hit("after_release")
        self.state.writes_since_snapshot = 0
        return Snapshot(
            shard=self.shard,
            last_lsn=last_lsn,
            fingerprint=written.fingerprint,
            path=written.path,
            published=True,
            records=written.records,
        )

    def stats(self) -> dict[str, Any]:
        data = self.state.stats()
        data.update(
            {
                "shard": self.shard,
                "wal_bytes": self.log.size_bytes(),
                "segments": len(self.log.segments),
                "next_lsn": self.counter.preview(),
                "snapshot_lsn": self.recovery.snapshot_lsn,
            }
        )
        return data

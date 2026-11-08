"""Moving a shard range from one replica to another.

A migration copies records, not keys, because a tombstone has to travel with
the rest or the receiving replica will resurrect it on the next read. It runs
in batches, checkpointing the last LSN it copied, so an interrupted migration
resumes instead of restarting.

Ordering rule: **the destination is caught up before the source is told it may
stop serving**. A migration that releases the source first creates a window in
which neither replica answers, and the store's quorum arithmetic turns that
into an unavailable key range. The phases are named in :data:`PHASES` and a
checkpoint records which one it finished, so a resumed migration can tell what
it still owes.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from .errors import MigrationError
from .values import Record

PHASES = ("planned", "streaming", "caught_up", "released", "done")


@dataclass
class Checkpoint:
    source: str
    destination: str
    shard: int
    last_lsn: int = 0
    copied: int = 0
    phase: str = "planned"
    batches: int = 0

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "destination": self.destination,
            "shard": self.shard,
            "last_lsn": self.last_lsn,
            "copied": self.copied,
            "phase": self.phase,
            "batches": self.batches,
        }

    @classmethod
    def load(cls, payload: dict) -> "Checkpoint":
        return cls(
            source=payload["source"],
            destination=payload["destination"],
            shard=int(payload["shard"]),
            last_lsn=int(payload.get("last_lsn", 0)),
            copied=int(payload.get("copied", 0)),
            phase=payload.get("phase", "planned"),
            batches=int(payload.get("batches", 0)),
        )


class MigrationJournal:
    """Checkpoints on disk, so an interrupted migration can be resumed."""

    def __init__(self, directory: pathlib.Path | str) -> None:
        self.directory = pathlib.Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, shard: int) -> pathlib.Path:
        return self.directory / f"migration-{shard:03d}.json"

    def write(self, checkpoint: Checkpoint) -> None:
        self.path_for(checkpoint.shard).write_text(
            json.dumps(checkpoint.as_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )

    def read(self, shard: int) -> Checkpoint | None:
        path = self.path_for(shard)
        if not path.exists():
            return None
        return Checkpoint.load(json.loads(path.read_text(encoding="utf-8")))

    def clear(self, shard: int) -> None:
        path = self.path_for(shard)
        if path.exists():
            path.unlink()


class Migrator:
    def __init__(self, nodes, *, config, journal: MigrationJournal | None = None) -> None:
        self.nodes = nodes
        self.config = config
        self.journal = journal

    def copy_range(
        self,
        shard: int,
        *,
        source: str,
        destination: str,
        keys=None,
        resume: bool = True,
    ) -> Checkpoint:
        """Copy records of one shard between replicas, in batches, with a checkpoint."""

        source_store = self.nodes[source].store(shard)
        destination_store = self.nodes[destination].store(shard)
        checkpoint = (self.journal.read(shard) if self.journal and resume else None) or Checkpoint(
            source=source, destination=destination, shard=shard
        )
        if checkpoint.source != source or checkpoint.destination != destination:
            raise MigrationError(
                f"checkpoint for shard {shard} belongs to {checkpoint.source}->"
                f"{checkpoint.destination}, not {source}->{destination}"
            )
        batch_size = int(self.config["migration_batch"])
        candidates = [
            record
            for record in source_store.state.all_records()
            if record.lsn > checkpoint.last_lsn and (keys is None or record.key in keys)
        ]
        checkpoint.phase = "streaming"
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            destination_store.apply_records(batch, reconcile=True)
            checkpoint.copied += len(batch)
            checkpoint.last_lsn = max(record.lsn for record in batch)
            checkpoint.batches += 1
            if self.journal is not None:
                self.journal.write(checkpoint)
        checkpoint.phase = "caught_up"
        if self.journal is not None:
            self.journal.write(checkpoint)
        return checkpoint

    def release(self, checkpoint: Checkpoint, *, keys=None) -> Checkpoint:
        """Let the source stop serving the migrated keys. Only after ``caught_up``."""

        if checkpoint.phase not in ("caught_up", "released", "done"):
            raise MigrationError(
                f"cannot release shard {checkpoint.shard} in phase {checkpoint.phase!r}; "
                "the destination has not been caught up"
            )
        source_store = self.nodes[checkpoint.source].store(checkpoint.shard)
        for key in list(source_store.state.keys()):
            if keys is not None and key not in keys:
                continue
            source_store.state.forget(key)
        checkpoint.phase = "released"
        if self.journal is not None:
            self.journal.write(checkpoint)
        return checkpoint

    def finish(self, checkpoint: Checkpoint) -> Checkpoint:
        checkpoint.phase = "done"
        if self.journal is not None:
            self.journal.write(checkpoint)
            self.journal.clear(checkpoint.shard)
        return checkpoint

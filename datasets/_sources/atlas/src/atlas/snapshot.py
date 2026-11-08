"""Snapshots and the CURRENT pointer: the publication decision.

A snapshot is a full image of one shard's memtable plus the LSN it is valid
at. Writing the file is not publishing it. **The CURRENT pointer file is the
publication decision**, and it is the only thing a recovering process
consults. Consequences that the recovery path has to honour:

* a snapshot file that exists but is not named by CURRENT is unpublished and
  must be ignored, not adopted;
* CURRENT may name a snapshot while older snapshot files still sit in the
  directory: they are stale, and pruning them is safe only after CURRENT has
  been fsynced onto its new name;
* publishing is atomic. A crash leaves either the old CURRENT or the new
  CURRENT, never a half-written one, which is why the pointer is written to a
  temporary file and renamed rather than truncated in place.

A shard recovers to ``snapshot.last_lsn`` and then applies the log strictly
after it, per the boundary convention in :mod:`atlas.clock`.
"""

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass

from .codec import canonical, checksum
from .errors import SnapshotError
from .values import Record
from .vclock import VersionVector

CURRENT_NAME = "CURRENT"
SNAPSHOT_PREFIX = "snapshot-"
SNAPSHOT_SUFFIX = ".snap"
#: A crash between writing the file and publishing it leaves this behind.
PENDING_SUFFIX = ".pending"


def snapshot_name(last_lsn: int, fingerprint: str) -> str:
    return f"{SNAPSHOT_PREFIX}{last_lsn:012d}-{fingerprint[:12]}{SNAPSHOT_SUFFIX}"


@dataclass(frozen=True)
class Snapshot:
    shard: int
    last_lsn: int
    fingerprint: str
    path: pathlib.Path
    published: bool
    records: tuple[Record, ...] = ()

    @property
    def key_count(self) -> int:
        return len(self.records)

    @property
    def tombstones(self) -> int:
        return sum(1 for record in self.records if record.deleted)


class SnapshotStore:
    def __init__(self, directory: pathlib.Path | str, *, fsync: bool = True) -> None:
        self.directory = pathlib.Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.fsync = fsync

    # ---------------------------------------------------------------- pointer
    def current_name(self) -> str | None:
        path = self.directory / CURRENT_NAME
        if not path.exists():
            return None
        name = path.read_text(encoding="utf-8").strip()
        return name or None

    def _publish(self, name: str) -> None:
        pointer = self.directory / CURRENT_NAME
        temporary = self.directory / f"{CURRENT_NAME}.tmp"
        temporary.write_text(name + "\n", encoding="utf-8")
        temporary.flush() if hasattr(temporary, "flush") else None
        with temporary.open("r+") as handle:
            handle.flush()
            if self.fsync:
                os.fsync(handle.fileno())
        os.replace(temporary, pointer)
        if self.fsync:
            self._fsync_directory()

    def _fsync_directory(self) -> None:
        flags = os.O_RDONLY
        handle = os.open(self.directory, flags)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)

    # ------------------------------------------------------------------ write
    def write(self, shard: int, records, *, last_lsn: int, publish: bool = True) -> Snapshot:
        payload = {
            "shard": int(shard),
            "last_lsn": int(last_lsn),
            "records": [_encode_record(record) for record in records],
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fingerprint = format(checksum(body), "08x")
        name = snapshot_name(last_lsn, fingerprint)
        path = self.directory / name
        with path.open("wb") as handle:
            handle.write(body)
            handle.flush()
            if self.fsync:
                os.fsync(handle.fileno())
        if publish:
            self._publish(name)
            pending = self.directory / (name + PENDING_SUFFIX)
            if pending.exists():
                pending.unlink()
        decoded = _decode(body, path)
        return Snapshot(
            shard=shard,
            last_lsn=last_lsn,
            fingerprint=fingerprint,
            path=path,
            published=publish and self.current_name() == name,
            records=decoded,
        )

    # ------------------------------------------------------------------- read
    def load_current(self) -> Snapshot | None:
        name = self.current_name()
        if name is None:
            return None
        path = self.directory / name
        if not path.exists():
            raise SnapshotError(
                f"CURRENT names {name!r} but that snapshot file is missing"
            )
        body = path.read_bytes()
        records = _decode(body, path)
        payload = json.loads(body.decode("utf-8"))
        return Snapshot(
            shard=int(payload["shard"]),
            last_lsn=int(payload["last_lsn"]),
            fingerprint=name.rsplit("-", 1)[-1][: -len(SNAPSHOT_SUFFIX)],
            path=path,
            published=True,
            records=records,
        )

    def candidates(self) -> list[pathlib.Path]:
        """Every snapshot file present, newest LSN first, published or not."""

        found = [
            path
            for path in self.directory.glob(f"{SNAPSHOT_PREFIX}*{SNAPSHOT_SUFFIX}")
        ]
        return sorted(found, key=lambda path: path.name, reverse=True)

    def superseded(self) -> list[pathlib.Path]:
        """Files older than the published one, safe to prune."""

        current = self.current_name()
        if current is None:
            return []
        return [path for path in self.candidates() if path.name != current]

    def prune(self, *, keep: int = 1) -> list[str]:
        current = self.current_name()
        if current is None:
            return []
        ordered = self.candidates()
        names = [current] + [path.name for path in ordered if path.name != current]
        doomed = names[max(1, int(keep)) :]
        removed = []
        for name in doomed:
            path = self.directory / name
            if path.exists():
                path.unlink()
                removed.append(name)
        return removed

    def adopt_latest_unpublished(self) -> Snapshot | None:
        """Publish the newest snapshot file. Recovery never calls this.

        It exists for an operator repairing a directory whose CURRENT was
        destroyed, and it is deliberately not wired into :meth:`load_current`:
        adopting an uncommitted snapshot would invent a publication decision
        the process never made.
        """

        for path in self.candidates():
            self._publish(path.name)
            return self.load_current()
        return None


def _encode_record(record: Record) -> dict:
    return {
        "key": record.key,
        "value": record.value,
        "gen": record.generation,
        "vec": dict(record.vector.counters),
        "deleted": record.deleted,
        "lsn": record.lsn,
        "at": record.written_at,
        "writer": record.writer,
        "attrs": [list(pair) for pair in record.attributes],
    }


def _decode(body: bytes, path: pathlib.Path) -> tuple[Record, ...]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"{path.name} is not readable JSON: {exc}") from exc
    records = []
    for item in payload.get("records", ()):
        records.append(
            Record(
                key=item["key"],
                value=item.get("value"),
                generation=int(item.get("gen", 1)),
                vector=VersionVector.new(item.get("vec") or {}),
                deleted=bool(item.get("deleted", False)),
                lsn=int(item.get("lsn", 0)),
                written_at=int(item.get("at", 0)),
                writer=item.get("writer", ""),
                attributes=tuple(tuple(pair) for pair in item.get("attrs") or ()),
            )
        )
    return tuple(records)

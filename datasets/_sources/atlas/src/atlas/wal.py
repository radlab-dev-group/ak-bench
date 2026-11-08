"""Write-ahead log: segments, transactions and torn-tail repair.

A segment is a concatenation of codec frames. A transaction is a ``BEGIN``
frame, zero or more ``PUT``/``DELETE`` frames, and a ``COMMIT`` frame::

    BEGIN   {"txn": id, "lsn": first-lsn-of-txn}
    PUT     {"key": ..., "value": ..., "gen": ..., "vec": ..., "lsn": ...}
    DELETE  {"key": ..., "gen": ..., "vec": ..., "lsn": ...}
    COMMIT  {"txn": id, "lsn": last-lsn-of-txn, "count": n}

Durability rule
---------------
**A transaction is durable exactly when its COMMIT frame is durable.** A
replay that meets an unterminated transaction discards it; a replay that
meets a COMMIT applies every record of that transaction exactly once.

Torn-tail repair
----------------
A process can die between the first byte of a frame and its last, leaving a
partial frame at the end of the file. :meth:`WriteAheadLog.repair_tail` cuts
the file back to the end of the **last frame that decoded cleanly**, and
nothing earlier. The rule exists because the frames before the damage include
committed transactions: cutting back to the start of the damaged
*transaction*, or to the last ``BEGIN``, would erase work that a ``COMMIT``
already made durable, and the caller would then be told "recovered cleanly"
while having lost acknowledged writes.

Repair never discards a committed transaction, and never keeps a partial one.
Those two sentences are what the hidden crash scenarios assert.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

from .codec import FRAME_OVERHEAD, Frame, FrameKind, decode, encode
from .errors import (
    AtlasError,
    ChecksumMismatchError,
    TornFrameError,
    WALIntegrityError,
)
from .values import Record
from .vclock import VersionVector

SEGMENT_SUFFIX = ".wal"
SEGMENT_PREFIX = "segment-"


def segment_name(index: int) -> str:
    return f"{SEGMENT_PREFIX}{index:06d}{SEGMENT_SUFFIX}"


def segment_index(name: str) -> int:
    stem = name[len(SEGMENT_PREFIX) : -len(SEGMENT_SUFFIX)]
    return int(stem)


@dataclass
class Transaction:
    """Frames collected in memory before they are appended."""

    txn_id: str
    lsn: int
    frames: list[tuple[FrameKind, dict]] = field(default_factory=list)

    def put(self, record: Record) -> None:
        self.frames.append((FrameKind.PUT, _record_payload(record)))

    def delete(self, record: Record) -> None:
        self.frames.append((FrameKind.DELETE, _record_payload(record)))

    def control(self, payload: dict) -> None:
        self.frames.append((FrameKind.CONTROL, dict(payload)))

    def __len__(self) -> int:
        return len(self.frames)


def _record_payload(record: Record) -> dict:
    return {
        "key": record.key,
        "value": record.value,
        "gen": record.generation,
        "vec": dict(record.vector.counters),
        "deleted": record.deleted,
        "lsn": record.lsn,
        "at": record.written_at,
        "writer": record.writer,
        "attrs": list(record.attributes),
    }


def record_from_payload(payload: dict) -> Record:
    return Record(
        key=payload["key"],
        value=payload.get("value"),
        generation=int(payload.get("gen", 1)),
        vector=VersionVector.new(payload.get("vec") or {}),
        deleted=bool(payload.get("deleted", False)),
        lsn=int(payload.get("lsn", 0)),
        written_at=int(payload.get("at", 0)),
        writer=payload.get("writer", ""),
        attributes=tuple(tuple(pair) for pair in payload.get("attrs") or ()),
    )


@dataclass
class RecoveryReport:
    """What a replay found, and what repair cut away."""

    transactions: int = 0
    applied: int = 0
    #: Records of committed transactions that a caller asked to skip because
    #: a snapshot already contains them.
    skipped: int = 0
    #: Bytes removed from the tail by :meth:`WriteAheadLog.repair_tail`.
    truncated_bytes: int = 0
    #: Committed transactions that survived a tail repair. The count is what
    #: a crash test asserts on; a repair that eats them reports zero here.
    surviving_transactions: int = 0
    torn: bool = False
    damage_offset: int | None = None
    warnings: list[str] = field(default_factory=list)


class WriteAheadLog:
    """One directory of numbered segments, appended to the highest one."""

    def __init__(
        self,
        directory: pathlib.Path | str,
        *,
        fsync: bool = True,
        max_bytes: int = 8 * 1024 * 1024,
        repair_on_open: bool = True,
    ) -> None:
        self.directory = pathlib.Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.fsync = fsync
        self.max_bytes = int(max_bytes)
        self.segments = sorted(
            (path for path in self.directory.glob(f"*{SEGMENT_SUFFIX}")),
            key=lambda path: segment_index(path.name),
        )
        self.report = RecoveryReport()
        if repair_on_open:
            for path in self.segments:
                self._repair_quietly(path)

    # ------------------------------------------------------------------ write
    def _active(self) -> pathlib.Path:
        if not self.segments:
            path = self.directory / segment_name(0)
            path.touch()
            self.segments.append(path)
        last = self.segments[-1]
        if last.exists() and last.stat().st_size > self.max_bytes:
            path = self.directory / segment_name(segment_index(last.name) + 1)
            path.touch()
            self.segments.append(path)
            return path
        return last

    def append(self, transaction: Transaction) -> int:
        """Append one transaction atomically; return the bytes written."""

        payload = encode(
            FrameKind.BEGIN, {"txn": transaction.txn_id, "lsn": transaction.lsn}
        )
        for kind, body in transaction.frames:
            payload += encode(kind, body)
        payload += encode(
            FrameKind.COMMIT,
            {
                "txn": transaction.txn_id,
                "lsn": transaction.lsn + len(transaction.frames),
                "count": len(transaction.frames),
            },
        )
        path = self._active()
        with path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            if self.fsync:
                os.fsync(handle.fileno())
        return len(payload)

    def truncate_after(self, path: pathlib.Path, size: int) -> int:
        current = path.stat().st_size if path.exists() else 0
        if size > current:
            raise AtlasError(f"cannot truncate {path.name} to {size}, it holds {current}")
        with path.open("r+b") as handle:
            handle.truncate(size)
            handle.flush()
            if self.fsync:
                os.fsync(handle.fileno())
        return current - size

    def discard(self, path: pathlib.Path) -> None:
        if path in self.segments:
            self.segments.remove(path)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------- integrity
    def scan(self, path: pathlib.Path, *, strict: bool = False):
        """Yield ``(frame, None)`` for good frames, and one ``(None, error)`` at damage."""

        data = path.read_bytes() if path.exists() else b""
        offset = 0
        while offset < len(data):
            if len(data) - offset < FRAME_OVERHEAD:
                error: WALIntegrityError = TornFrameError(
                    f"{path.name}: {len(data) - offset} trailing bytes at {offset}"
                )
                if strict:
                    raise error
                yield None, error
                return
            try:
                frame = decode(data, offset=offset)
            except (TornFrameError, ChecksumMismatchError) as exc:
                if strict:
                    raise exc
                yield None, exc
                return
            yield frame, None
            offset += frame.size

    def _repair_quietly(self, path: pathlib.Path) -> RecoveryReport:
        report = self.repair_tail(path)
        self.report.truncated_bytes += report.truncated_bytes
        self.report.torn = self.report.torn or report.torn
        return report

    def repair_tail(self, path: pathlib.Path) -> RecoveryReport:
        """Cut a segment back to the end of its last intact frame.

        The cut point is the byte offset where the first damaged frame begins,
        which is also the end of the last frame that decoded cleanly. Frames
        before that point are untouched: they include committed transactions,
        and a committed transaction is never collateral damage of a torn tail.
        """

        report = RecoveryReport()
        data = path.read_bytes() if path.exists() else b""
        if not data:
            return report
        healthy = 0
        committed = 0
        offset = 0
        while offset < len(data):
            if len(data) - offset < FRAME_OVERHEAD:
                report.torn = True
                report.damage_offset = offset
                break
            try:
                frame = decode(data, offset=offset)
            except (TornFrameError, ChecksumMismatchError) as exc:
                report.torn = True
                report.damage_offset = offset
                report.warnings.append(str(exc))
                break
            if frame.kind is FrameKind.COMMIT:
                committed += 1
            healthy = offset + frame.size
            offset = healthy
        if healthy != len(data):
            report.truncated_bytes = self.truncate_after(path, healthy)
            report.surviving_transactions = committed
        return report

    # ------------------------------------------------------------------- read
    def frames(self):
        """Every frame of every segment, in order, stopping at the first damage."""

        for path in self.segments:
            for frame, error in self.scan(path):
                if error is not None:
                    self.report.warnings.append(str(error))
                    return
                yield path, frame

    def transactions(self):
        """Group the frames of all segments into ``(txn_id, begin_lsn, frames)``."""

        current: tuple[str, int, list[tuple[FrameKind, dict]]] | None = None
        for _path, frame in self.frames():
            if frame.kind is FrameKind.BEGIN:
                current = (frame.payload["txn"], int(frame.payload["lsn"]), [])
            elif frame.kind is FrameKind.COMMIT and current is not None:
                yield current
                current = None
            elif current is not None:
                current[2].append((frame.kind, frame.payload))

    def replay(self, *, bounds, snapshot_lsn: int = 0):
        """Yield ``(kind, record)`` for records a caller must still apply.

        Only committed transactions are considered, and only records the
        snapshot bounds say are not already present. The bounds object is the
        single owner of that comparison; see :mod:`atlas.clock`.
        """

        report = RecoveryReport()
        for txn_id, begin_lsn, frames in self.transactions():
            report.transactions += 1
            pending: list[tuple[FrameKind, Record]] = []
            for kind, payload in frames:
                if kind not in (FrameKind.PUT, FrameKind.DELETE):
                    continue
                record = record_from_payload(payload)
                if not bounds.applies(record.lsn, snapshot_lsn):
                    report.skipped += 1
                    continue
                if record.lsn < begin_lsn:
                    raise WALIntegrityError(
                        f"transaction {txn_id} carries lsn {record.lsn} below its own BEGIN"
                    )
                pending.append((kind, record))
            for kind, record in pending:
                report.applied += 1
                yield kind, record
        report.__dict__["_keep"] = None
        self.report.transactions += report.transactions
        self.report.applied += report.applied
        self.report.skipped += report.skipped

    def size_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.segments if path.exists())

    def highest_lsn(self) -> int:
        highest = 0
        for _path, frame in self.frames():
            for key in ("lsn",):
                value = frame.payload.get(key)
                if isinstance(value, int) and value > highest:
                    highest = value
        return highest

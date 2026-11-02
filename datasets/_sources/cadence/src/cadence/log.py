"""A write-ahead log the process can be killed in the middle of.

Records are appended as one JSON object per line, each carrying the sequence
number it was given and a checksum of its own body. The log is the only reason
the engine can be restarted: state that exists only in memory is state a crash
takes with it, and a scheduler that forgets what it already ran runs it twice.

The rules
    * A record is ``lsn`` (a one-based sequence number), ``kind``, ``at`` (the
      wall-clock time the caller stated) and ``payload``. The lsn of an appended
      record is one more than the highest lsn in the file, so a record that was
      dropped by a truncation never has its number reused.
    * A line whose checksum does not match its body, or which cannot be parsed
      at all, is a **torn tail**: a crash mid-write. Reading stops there and
      the broken remainder is dropped, because a half-written record is a record
      that never happened. A torn tail is not an error to raise on; it is the
      expected shape of a log after a hard kill.
    * ``append`` with an ``idempotency_key`` that is already in the log writes
      nothing and returns the record that holds the key. Retrying an operation
      after a crash is therefore safe to express at the log level.
    * ``truncate_before(lsn)`` drops the records below ``lsn`` and rewrites the
      file with its numbers intact. ``compact`` uses it after folding history.
    * A payload must be JSON-shaped; the log does not accept a Python object it
      could not write back, because a record that cannot be read is a record
      that will not survive the restart it was written for.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cadence.errors import CorruptedLog

CHECKSUM_KEY = "digest"


def _checksum(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Record:
    """One entry of the log."""

    lsn: int
    kind: str
    at: float
    payload: dict[str, Any] = field(default_factory=dict)
    digest: str = ""

    @property
    def key(self) -> str | None:
        value = self.payload.get("idempotency_key")
        return None if value is None else str(value)

    def body(self) -> dict[str, Any]:
        return {"lsn": self.lsn, "kind": self.kind, "at": self.at, "payload": self.payload}

    def is_intact(self) -> bool:
        return self.digest == _checksum(self.body())


class WriteAheadLog:
    """Append-only log in one file, readable up to the last whole record."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        self._dropped = 0

    # reading ---------------------------------------------------------------

    def records(self, *, from_lsn: int = 0) -> list[Record]:
        """Every intact record at or above ``from_lsn``, in append order."""
        found: list[Record] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.rstrip("\n")
                if not line:
                    continue
                record = self._parse(line)
                if record is None:
                    # a torn tail: nothing written after it can be trusted
                    self._dropped += 1
                    break
                if not record.is_intact():
                    self._dropped += 1
                    break
                if record.lsn >= from_lsn:
                    found.append(record)
        return found

    def last(self) -> Record | None:
        records = self.records()
        return records[-1] if records else None

    def next_lsn(self) -> int:
        highest = max((record.lsn for record in self.records()), default=0)
        return highest + 1

    def dropped(self) -> int:
        """How many broken lines the last read cut away."""
        return self._dropped

    def keys(self) -> set[str]:
        return {key for key in (record.key for record in self.records()) if key is not None}

    # writing ---------------------------------------------------------------

    def append(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        at: float,
        idempotency_key: str | None = None,
    ) -> Record:
        """Write one record, or return the one an earlier call already wrote."""
        body = dict(payload or {})
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
            existing = self.find_key(idempotency_key)
            if existing is not None:
                return existing
        record = Record(lsn=self.next_lsn(), kind=kind, at=at, payload=body)
        record = Record(
            lsn=record.lsn,
            kind=record.kind,
            at=record.at,
            payload=record.payload,
            digest=_checksum(record.body()),
        )
        self._write(record)
        return record

    def find_key(self, key: str) -> Record | None:
        for record in self.records():
            if record.key == key:
                return record
        return None

    def truncate_before(self, lsn: int) -> int:
        """Drop every record below ``lsn``; return how many went away."""
        kept = [record for record in self.records() if record.lsn >= lsn]
        removed = len(self.records()) - len(kept)
        self._rewrite(kept)
        return removed

    def size(self) -> int:
        return len(self.records())

    # internals -------------------------------------------------------------

    @staticmethod
    def _parse(line: str) -> Record | None:
        try:
            raw = json.loads(line)
            payload = dict(raw.get("payload") or {})
            return Record(
                lsn=int(raw["lsn"]),
                kind=str(raw["kind"]),
                at=float(raw["at"]),
                payload=payload,
                digest=str(raw.get(CHECKSUM_KEY, "")),
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

    def _write(self, record: Record) -> None:
        line = json.dumps(
            {**record.body(), CHECKSUM_KEY: record.digest},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _rewrite(self, records: list[Record]) -> None:
        handle, temp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".log.tmp")
        temp = Path(temp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                for record in records:
                    stream.write(
                        json.dumps(
                            {**record.body(), CHECKSUM_KEY: record.digest},
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()

    def verify(self) -> list[str]:
        """Problems a reader would hit; empty means the log is readable to the end."""
        problems: list[str] = []
        previous = 0
        for index, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            record = self._parse(line)
            if record is None:
                problems.append(f"line {index}: unparseable record")
                continue
            if not record.is_intact():
                problems.append(f"line {index}: checksum mismatch at lsn {record.lsn}")
            if record.lsn <= previous:
                problems.append(f"line {index}: lsn {record.lsn} does not follow {previous}")
            previous = record.lsn
        return problems


def fold(records: list[Record], *, kind: str) -> dict[str, dict[str, Any]]:
    """The last payload per ``payload['subject']`` for every record of ``kind``."""
    folded: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.kind != kind:
            continue
        subject = record.payload.get("subject")
        if subject is None:
            raise CorruptedLog(f"{kind} record at lsn {record.lsn} states no subject")
        folded[str(subject)] = record.payload
    return folded

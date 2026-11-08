"""The value model: writes, tombstones and generations.

A stored value is a :class:`Record`. Records are immutable; every mutation of
a key produces a new record with a strictly greater ``generation``. The
generation is the fencing token of the write path: a caller that read a key
at generation ``g`` may only commit an update that offers ``g`` back, and the
store accepts it only while ``g`` is still the current generation.

Deletion is a tombstone, not an absence. A tombstone carries the generation
of the write that removed the value, and a tombstone is terminal: a write
that offers an older generation cannot resurrect a deleted key.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Self

from .errors import StaleGenerationError
from .vclock import VersionVector

#: A value is JSON-encodable plus these primitives; the codec owns the wire
#: form, the record owns the semantics.
MISSING = object()


@dataclass(frozen=True)
class Record:
    """One immutable version of one key.

    ``generation``
        Monotonic per-key counter owned by the primary replica. The fencing
        check is an equality test against the generation the caller offered.
    ``vector``
        Version vector of the write; causality between replicas.
    ``deleted``
        Tombstone marker. ``value`` is ``None`` when set.
    ``lsn``
        Log sequence number of the WAL frame that made this write durable.
        Zero before the write has been logged.
    """

    key: str
    value: Any = None
    generation: int = 1
    vector: VersionVector = field(default_factory=VersionVector.new)
    deleted: bool = False
    lsn: int = 0
    written_at: int = 0
    writer: str = ""
    attributes: tuple[tuple[str, str], ...] = ()

    @classmethod
    def put(
        cls,
        key: str,
        value: Any,
        *,
        generation: int = 1,
        vector: VersionVector | None = None,
        writer: str = "local",
        lsn: int = 0,
        written_at: int | None = None,
        attributes: dict[str, str] | None = None,
    ) -> Self:
        return cls(
            key=key,
            value=value,
            generation=generation,
            vector=vector if vector is not None else VersionVector.single(writer),
            deleted=False,
            lsn=lsn,
            written_at=int(time.time() * 1000) if written_at is None else int(written_at),
            writer=writer,
            attributes=tuple(sorted((attributes or {}).items())),
        )

    @classmethod
    def tombstone(
        cls,
        key: str,
        *,
        generation: int,
        vector: VersionVector,
        writer: str = "local",
        lsn: int = 0,
        written_at: int | None = None,
    ) -> Self:
        return cls(
            key=key,
            value=None,
            generation=generation,
            vector=vector,
            deleted=True,
            lsn=lsn,
            written_at=int(time.time() * 1000) if written_at is None else int(written_at),
            writer=writer,
        )

    @property
    def is_tombstone(self) -> bool:
        return self.deleted

    @property
    def attribute_map(self) -> dict[str, str]:
        return dict(self.attributes)

    def advance(
        self,
        value: Any,
        *,
        writer: str,
        lsn: int = 0,
        deleted: bool = False,
        attributes: dict[str, str] | None = None,
    ) -> Self:
        """Return the next version of this record, one generation ahead."""

        merged = self.attribute_map
        merged.update(attributes or {})
        return replace(
            self,
            value=None if deleted else value,
            generation=self.generation + 1,
            vector=self.vector.increment(writer),
            deleted=deleted,
            lsn=lsn,
            writer=writer,
            attributes=tuple(sorted(merged.items())),
        )

    def check_offers(self, offered: int) -> None:
        """Raise :class:`StaleGenerationError` unless ``offered`` is current.

        The comparison is an equality test, deliberately. A greater offered
        generation means the caller has seen a version this replica does not,
        which is a protocol violation of the same class as a smaller one.
        """

        if offered != self.generation:
            raise StaleGenerationError(self.key, offered, self.generation)

    def render(self) -> str:
        state = "tombstone" if self.deleted else repr(self.value)
        return (
            f"Record({self.key!r} {state} gen={self.generation} "
            f"vec={self.vector.render()} lsn={self.lsn} writer={self.writer})"
        )


def live(records) -> list[Record]:
    """Filter out tombstones, keeping the caller's order."""

    return [record for record in records if not record.deleted]


def newest(records) -> Record | None:
    best: Record | None = None
    for record in records:
        if best is None or record.generation > best.generation:
            best = record
    return best

"""The log sequence and a monotonic hybrid clock.

The LSN is the store's only notion of "after". Every durable write takes the
next integer from a single monotonic counter, and every boundary decision —
what a snapshot already contains, what a replay must skip, what a migration
has already copied — is expressed as a comparison against an LSN.

Two properties are load bearing:

* the counter never goes backwards and never repeats within a node;
* an LSN is meaningless without its boundary convention. ``contains(lsn)``
  below is the single place that convention lives, and the configuration key
  ``compaction_lsn_boundary`` selects it. The default is **exclusive**: a
  snapshot taken at ``last_lsn = N`` already contains record ``N``, so replay
  applies records strictly greater than ``N``.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass

LSN_EXCLUSIVE = "exclusive"
LSN_INCLUSIVE = "inclusive"
_BOUNDARIES = (LSN_EXCLUSIVE, LSN_INCLUSIVE)


class MonotonicCounter:
    """A thread-safe, never-regressing integer source with a floor."""

    def __init__(self, start: int = 0) -> None:
        if start < 0:
            raise ValueError("an LSN counter cannot start below zero")
        self._value = int(start)
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        return self._value

    def next(self) -> int:
        with self._lock:
            self._value += 1
            return self._value

    def advance_to(self, floor: int) -> int:
        """Raise the counter to ``floor`` if it is behind. Never lowers it."""

        with self._lock:
            if floor > self._value:
                self._value = int(floor)
            return self._value

    def preview(self) -> int:
        return self._value + 1


class HybridClock:
    """Milliseconds since epoch, guaranteed monotonic within the process.

    Wall time is what a tombstone's grace period is measured against, so it
    has to be comparable across restarts; monotonic time is what keeps
    same-millisecond writes ordered. This returns the wall clock, advanced by
    one millisecond whenever the wall clock has not moved.
    """

    def __init__(self, source=time.time) -> None:
        self._source = source
        self._last = 0
        self._lock = threading.Lock()

    def now_ms(self) -> int:
        with self._lock:
            current = int(self._source() * 1000)
            if current <= self._last:
                current = self._last + 1
            self._last = current
            return current


@dataclass(frozen=True)
class LSNBounds:
    """The one spelling of "is this record already in the snapshot"."""

    boundary: str = LSN_EXCLUSIVE

    def __post_init__(self) -> None:
        if self.boundary not in _BOUNDARIES:
            raise ValueError(f"boundary must be one of {_BOUNDARIES}, got {self.boundary!r}")

    def applies(self, record_lsn: int, snapshot_lsn: int) -> bool:
        """True when a record must still be applied on top of a snapshot at ``snapshot_lsn``."""

        if self.boundary == LSN_EXCLUSIVE:
            return record_lsn > snapshot_lsn
        return record_lsn >= snapshot_lsn

    @classmethod
    def from_config(cls, config) -> "LSNBounds":
        return cls(boundary=config["compaction_lsn_boundary"])


#: The sequence helper the WAL uses to hand out LSNs inside a transaction.
def sequence(start: int = 0):
    return itertools.count(start + 1)

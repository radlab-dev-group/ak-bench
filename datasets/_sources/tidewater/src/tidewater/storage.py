"""Persistent state per node, with a durability seam for crash tests.

Raft's persistence contract (``SPEC.md`` section 5) is small: ``current_term``,
``voted_for`` and the log must be durable *before* the node sends any message
that depends on them. The commit index and the applied state are volatile and
are rebuilt after a restart.

A real server fsyncs. This simulator has no disk, so :class:`Storage` keeps
two copies of the state: ``_volatile``, which the node writes to, and
``_durable``, which only :meth:`Storage.sync` updates. A crash
(:meth:`Storage.crash`) throws the volatile copy away and the node restarts
from the durable one. The node calls ``sync()`` at the points the contract
names; a test that wants to prove the contract matters can construct the
storage with ``sync_policy="never"``, in which case ``sync()`` is a no-op and
a crash loses everything since the last... nothing — which is exactly the
failure mode ``docs/incidents/INC-0003`` describes.

``sync_policy`` values:

``"always"``  every write is durable immediately (the default; models a
              server that fsyncs each write);
``"explicit"`` writes become durable at ``sync()`` (models group commit; the
              node's sync points are then what matters);
``"never"``   ``sync()`` does nothing (a broken server; for tests).

``sync_count`` and ``write_count`` are exposed so a test can assert that a
node synced before replying rather than merely that the final state is right.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .errors import ConfigurationError, StorageError
from .log import Entry, RaftLog, entry_from_dict

SYNC_POLICIES = ("always", "explicit", "never")


@dataclass
class SnapshotRecord:
    """The durable form of a snapshot (``SPEC.md`` section 6, declared). The
    seed only ever stores ``None`` here; the fields are fixed now so that the
    storage format does not change when snapshots arrive."""

    last_included_index: int
    last_included_term: int
    state: bytes
    config: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_included_index": self.last_included_index,
            "last_included_term": self.last_included_term,
            "state": self.state.hex(),
            "config": list(self.config),
        }


@dataclass
class PersistentState:
    """What survives a crash."""

    current_term: int = 0
    voted_for: str | None = None
    entries: list[Entry] = field(default_factory=list)
    base_index: int = 0
    base_term: int = 0
    snapshot: SnapshotRecord | None = None
    voters: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_term": self.current_term,
            "voted_for": self.voted_for,
            "entries": [e.to_dict() for e in self.entries],
            "base_index": self.base_index,
            "base_term": self.base_term,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "voters": list(self.voters),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PersistentState":
        snap = data.get("snapshot")
        return cls(
            current_term=int(data.get("current_term", 0)),
            voted_for=data.get("voted_for"),
            entries=[entry_from_dict(e) for e in data.get("entries", [])],
            base_index=int(data.get("base_index", 0)),
            base_term=int(data.get("base_term", 0)),
            snapshot=SnapshotRecord(
                last_included_index=int(snap["last_included_index"]),
                last_included_term=int(snap["last_included_term"]),
                state=bytes.fromhex(snap["state"]),
                config=tuple(snap["config"]),
            )
            if snap
            else None,
            voters=tuple(data.get("voters", ())),
        )


class Storage:
    """The durability seam. One per node."""

    def __init__(self, node_id: str, voters: tuple[str, ...], sync_policy: str = "always") -> None:
        if sync_policy not in SYNC_POLICIES:
            raise ConfigurationError(f"unknown sync policy {sync_policy!r}; expected one of {SYNC_POLICIES}")
        self.node_id = node_id
        self.sync_policy = sync_policy
        self._volatile = PersistentState(voters=tuple(voters))
        self._durable = copy.deepcopy(self._volatile)
        self.write_count = 0
        self.sync_count = 0
        self.crash_count = 0
        self.lost_writes = 0
        self._dirty = False

    # -- reads ------------------------------------------------------------

    @property
    def current_term(self) -> int:
        return self._volatile.current_term

    @property
    def voted_for(self) -> str | None:
        return self._volatile.voted_for

    @property
    def voters(self) -> tuple[str, ...]:
        return self._volatile.voters

    @property
    def snapshot(self) -> SnapshotRecord | None:
        return self._volatile.snapshot

    def load_log(self) -> RaftLog:
        """A fresh :class:`RaftLog` built from the volatile state. The node
        owns the returned log and writes it back through :meth:`save_log`."""

        return RaftLog(
            entries=self._volatile.entries,
            base_index=self._volatile.base_index,
            base_term=self._volatile.base_term,
        )

    def durable_view(self) -> PersistentState:
        """A copy of what a crash would leave behind. For tests."""

        return copy.deepcopy(self._durable)

    @property
    def dirty(self) -> bool:
        return self._dirty

    # -- writes -----------------------------------------------------------

    def _wrote(self) -> None:
        self.write_count += 1
        if self.sync_policy == "always":
            self._durable = copy.deepcopy(self._volatile)
            self._dirty = False
        else:
            self._dirty = True

    def set_term(self, term: int, voted_for: str | None) -> None:
        """Record a new term and the vote in it (``None`` for no vote). The
        term never decreases; a vote is only recorded for the current term."""

        if term < self._volatile.current_term:
            raise StorageError(f"{self.node_id}: term cannot decrease ({self._volatile.current_term} -> {term})")
        if term == self._volatile.current_term and self._volatile.voted_for not in (None, voted_for):
            raise StorageError(
                f"{self.node_id}: already voted for {self._volatile.voted_for} in term {term}, "
                f"cannot vote for {voted_for}"
            )
        self._volatile.current_term = term
        self._volatile.voted_for = voted_for
        self._wrote()

    def save_log(self, log: RaftLog) -> None:
        self._volatile.entries = list(log.entries())
        self._volatile.base_index = log.base_index
        self._volatile.base_term = log.base_term
        self._wrote()

    def save_snapshot(self, record: SnapshotRecord | None) -> None:
        self._volatile.snapshot = record
        self._wrote()

    def save_voters(self, voters: tuple[str, ...]) -> None:
        self._volatile.voters = tuple(voters)
        self._wrote()

    def sync(self) -> bool:
        """Make the volatile state durable. Returns True if anything was
        actually written through; False under the ``never`` policy."""

        self.sync_count += 1
        if self.sync_policy == "never":
            return False
        self._durable = copy.deepcopy(self._volatile)
        self._dirty = False
        return True

    # -- crash ------------------------------------------------------------

    def crash(self) -> PersistentState:
        """Lose the volatile state; return what the node will restart from."""

        self.crash_count += 1
        if self._dirty:
            self.lost_writes += 1
        self._volatile = copy.deepcopy(self._durable)
        self._dirty = False
        return self._volatile

    def describe(self) -> str:
        return (
            f"{self.node_id} storage[{self.sync_policy}] term={self.current_term} vote={self.voted_for} "
            f"entries={len(self._volatile.entries)} base={self._volatile.base_index}/{self._volatile.base_term} "
            f"writes={self.write_count} syncs={self.sync_count} crashes={self.crash_count} "
            f"dirty={'yes' if self._dirty else 'no'}"
        )

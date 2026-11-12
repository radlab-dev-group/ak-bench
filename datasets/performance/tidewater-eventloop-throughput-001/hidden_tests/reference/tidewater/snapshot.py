"""Snapshots and log compaction.

.. note::
   **This feature is not implemented.** The functions and classes below
   declare the contract; every one that would do work raises
   :class:`~tidewater.errors.FeatureNotImplemented`. The contract is
   complete and normative: ``SPEC.md`` section 6 is the acceptance rule and
   ``docs/adr/ADR-0006`` and ``ADR-0011`` are the reasoning. An
   implementation is judged against the spec, not against these stubs. The
   seed runs with ``compaction_threshold = 0``, which never calls in here.

The shape of the feature, as the spec fixes it:

1. **When** — a node whose log holds at least ``threshold`` entries *and*
   whose applied index is past the current compaction boundary takes a
   snapshot of its state machine at ``last_applied``. Snapshots are taken
   by every node independently; there is no leader-driven snapshot.
2. **What** — a :class:`~tidewater.storage.SnapshotRecord`: the canonical
   state bytes, ``last_included_index = last_applied``,
   ``last_included_term = log.term_at(last_applied)``, and the configuration
   in force at that index. The record is saved and synced before the log
   is compacted (``SPEC.md`` 6.2), so a crash between the two leaves a
   longer log and a usable snapshot, never a shorter log and no snapshot.
3. **Compaction** — ``RaftLog.compact_to(last_included_index,
   last_included_term)`` drops the prefix and keeps the boundary term so
   that log matching at the boundary still works (``ADR-0011``: the term is
   what lets a follower whose ``prev_log_index`` equals the boundary accept
   the first append after a snapshot).
4. **Transfer** — a leader whose ``next_index[peer] <= log.first_index``
   sends :class:`~tidewater.messages.InstallSnapshot` in chunks of
   ``chunk_size`` bytes, in order, waiting for the ack of each before the
   next. The follower's :class:`~tidewater.messages.InstallSnapshotResponse`
   carries the next offset it expects; the leader resumes from the
   follower's offset, not from its own counter (``SPEC.md`` 6.5).
5. **Install** — on the final chunk (``done``) the follower: discards its
   entire log if ``last_included_index`` is beyond it or conflicts in term,
   otherwise keeps the suffix after the boundary; replaces the state machine
   with the snapshot state; sets ``commit_index`` and ``last_applied`` to
   ``last_included_index``; saves and syncs the record before replying.
6. **Crash mid-transfer** — a follower that restarts with a partial
   transfer discards the partial chunks (they are volatile) and answers the
   next chunk with ``offset = 0``; the leader restarts the transfer. A
   leader that restarts is a leader no longer, and the new leader will
   begin its own transfer if the follower still needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .errors import FeatureNotImplemented
from .messages import InstallSnapshot, InstallSnapshotResponse
from .storage import SnapshotRecord

if TYPE_CHECKING:  # pragma: no cover
    from .node import Node

#: Default chunk size in bytes. Small on purpose: the simulator wants to
#: see multi-chunk transfers in a short run.
DEFAULT_CHUNK_SIZE = 64


@dataclass(frozen=True)
class SnapshotPolicy:
    """When to compact and how to ship.

    ``threshold`` is the log length (entries, not bytes) at which a node
    snapshots; zero disables. ``chunk_size`` is the transfer chunk.
    ``keep_entries`` is how many entries *after* the boundary a node keeps
    for followers that are only slightly behind, so the common case does
    not pay for a snapshot transfer; it is a lower bound on the suffix.
    """

    threshold: int = 0
    chunk_size: int = DEFAULT_CHUNK_SIZE
    keep_entries: int = 8

    def __post_init__(self) -> None:
        if self.threshold < 0 or self.chunk_size < 1 or self.keep_entries < 0:
            raise ValueError("snapshot policy fields are non-negative, and chunk_size is at least 1")

    @property
    def enabled(self) -> bool:
        return self.threshold > 0


@dataclass
class SnapshotTransfer:
    """Leader-side progress of one transfer to one follower.

    ``offset`` is the next byte to send and is corrected from every ack.
    ``record`` is pinned for the whole transfer: a newer snapshot taken
    mid-transfer does not switch the stream, it starts a new transfer once
    this one is done or abandoned.
    """

    peer: str
    record: SnapshotRecord
    offset: int = 0
    chunks_sent: int = 0
    done: bool = False


@dataclass
class PendingInstall:
    """Follower-side volatile buffer of a transfer in progress. Lost on
    crash by design (contract point 6)."""

    leader_id: str
    last_included_index: int
    last_included_term: int
    received: bytearray
    next_offset: int = 0


def take_snapshot(node: "Node", policy: SnapshotPolicy) -> SnapshotRecord:  # pragma: no cover - contract stub
    """Snapshot ``node``'s state machine at ``last_applied`` and compact.

    Order of effects, which is the whole of ``SPEC.md`` 6.2:

    1. build the :class:`SnapshotRecord` at ``node.state_machine.last_applied``
       with ``last_included_term = node.log.term_at(last_applied)`` and the
       voters of ``node.config``;
    2. ``node.storage.save_snapshot(record)``; ``node.storage.sync()``;
    3. ``node.log.compact_to(last_applied - policy.keep_entries, ...)`` if
       that boundary is above the current base (never compact past
       ``last_applied``; keep at least ``keep_entries`` after the boundary);
    4. ``node.storage.save_log(node.log)``; ``node.storage.sync()``;
    5. record a ``snapshot`` trace event with the boundary.

    Returns the record.
    """

    raise FeatureNotImplemented("snapshots are not implemented")


def send_snapshot_chunk(node: "Node", peer: str, offset: int) -> InstallSnapshot:  # pragma: no cover
    """Leader side: build and enqueue the chunk at ``offset`` of the current
    snapshot for ``peer``, creating a :class:`SnapshotTransfer` if none is
    in flight. ``done`` is true when ``offset + len(chunk) >= len(state)``."""

    raise FeatureNotImplemented("snapshots are not implemented")


def receive_snapshot_chunk(node: "Node", src: str, msg: InstallSnapshot) -> InstallSnapshotResponse:  # pragma: no cover
    """Follower side (contract point 5 and 6). A chunk whose ``offset``
    differs from the expected one is answered with the expected offset and
    otherwise ignored. On ``done``: install, sync, reply with
    ``done=True``."""

    raise FeatureNotImplemented("snapshots are not implemented")


def on_snapshot_ack(node: "Node", src: str, msg: InstallSnapshotResponse) -> None:  # pragma: no cover
    """Leader side: advance (or rewind) the transfer to ``msg.offset``; on
    ``msg.done`` set ``next_index[peer] = last_included_index + 1`` and
    ``match_index[peer] = last_included_index`` and resume ``AppendEntries``."""

    raise FeatureNotImplemented("snapshots are not implemented")


def resume_after_restart(node: "Node") -> None:  # pragma: no cover - contract stub
    """Called by ``Node.restart`` once snapshots exist: if storage holds a
    snapshot, load the state machine from it and set ``last_applied`` and
    ``commit_index`` to ``last_included_index`` before replaying the log
    suffix. The seed's ``restart`` rebuilds from index 1 because the seed
    never holds a snapshot."""

    raise FeatureNotImplemented("snapshots are not implemented")

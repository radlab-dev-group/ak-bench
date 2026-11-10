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

from .errors import FeatureNotImplemented, StorageError
from .log import RaftLog
from .messages import InstallSnapshot, InstallSnapshotResponse
from .statemachine import KVStateMachine
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
    in_flight: bool = False


@dataclass
class PendingInstall:
    """Follower-side volatile buffer of a transfer in progress. Lost on
    crash by design (contract point 6)."""

    leader_id: str
    last_included_index: int
    last_included_term: int
    received: bytearray
    next_offset: int = 0


def take_snapshot(node: "Node", policy: SnapshotPolicy) -> SnapshotRecord:
    """Snapshot ``node``'s state machine at ``last_applied`` and compact.

    Order of effects, which is the whole of ``SPEC.md`` 6.2: build the record,
    save and sync it, compact the log, save and sync the log, trace. A crash
    between the two syncs therefore leaves a longer log and a usable snapshot.
    """

    last_applied = node.state_machine.last_applied
    if last_applied <= node.log.base_index:
        recorded = node.storage.snapshot
        if recorded is not None:
            return recorded
        raise StorageError(
            f"{node.node_id}: nothing is applied past boundary {node.log.base_index}, so there is nothing to snapshot"
        )
    boundary_term = node.log.term_at(last_applied)
    if boundary_term is None:
        raise StorageError(f"{node.node_id}: index {last_applied} is not covered by the log")
    record = SnapshotRecord(
        last_included_index=last_applied,
        last_included_term=boundary_term,
        state=node.state_machine.snapshot_bytes(),
        config=tuple(node.config.sorted_voters()),
    )
    node.storage.save_snapshot(record)
    node.storage.sync()
    dropped = 0
    boundary = last_applied - policy.keep_entries
    if boundary > node.log.base_index:
        dropped = node.log.compact_to(boundary, node.log.term_at(boundary))
        node.storage.save_log(node.log)
        node.storage.sync()
    node.trace.record(node.global_tick, node.node_id, "snapshot",
                      last_included_index=record.last_included_index,
                      last_included_term=record.last_included_term,
                      dropped=dropped)
    return record


def resume_after_restart(node: "Node") -> SnapshotRecord | None:
    """Come back from the snapshot rather than from index 1 (``SPEC.md`` 6.6).

    Called by ``Node.restart`` once the volatile state has been rebuilt from
    storage: the record carries everything up to its boundary, so the node
    resumes with the state machine the record holds, starts at
    ``commit_index = last_included_index``, and replays only the suffix.
    """

    record = node.storage.snapshot
    if record is None:
        return None
    node.log = node.storage.load_log()
    state_machine = KVStateMachine.from_snapshot_bytes(record.state)
    state_machine.last_applied = record.last_included_index
    node.state_machine = state_machine
    node.commit_index = max(node.commit_index, record.last_included_index)
    node.pending_installs.clear()
    node.trace.record(node.global_tick, node.node_id, "snapshot_resumed",
                      last_included_index=record.last_included_index,
                      last_included_term=record.last_included_term,
                      base_index=node.log.base_index, last_index=node.log.last_index)
    return record

def send_snapshot_chunk(node: "Node", peer: str, offset: int) -> InstallSnapshot:
    """Leader side: enqueue the chunk at ``offset`` of the snapshot in flight
    for ``peer`` (``SPEC.md`` 6.4).

    The record is pinned when the transfer opens, so a snapshot taken while
    bytes are on the wire does not switch the stream mid-flight. ``done`` is
    set on the chunk that carries the last byte.
    """

    record = node.storage.snapshot
    if record is None:
        raise StorageError(f"{node.node_id}: there is no snapshot to send to {peer}")
    transfer = node.snapshot_transfers.get(peer)
    if transfer is None:
        transfer = SnapshotTransfer(peer=peer, record=record)
        node.snapshot_transfers[peer] = transfer
    record = transfer.record
    transfer.offset = offset
    chunk = record.state[offset:offset + node.snapshot_policy.chunk_size]
    done = offset + len(chunk) >= len(record.state)
    message = InstallSnapshot(
        term=node.current_term, leader_id=node.node_id,
        last_included_index=record.last_included_index,
        last_included_term=record.last_included_term,
        offset=offset, data=chunk, done=done,
    )
    transfer.chunks_sent += 1
    node.outbox.append((peer, message))
    return message


def _install_response(node: "Node", offset: int, done: bool = False) -> InstallSnapshotResponse:
    return InstallSnapshotResponse(term=node.current_term, follower_id=node.node_id,
                                   offset=offset, done=done)


def _install(node: "Node", record: SnapshotRecord) -> int:
    """``SPEC.md`` 6.5, the part that decides what the follower keeps.

    The suffix after the boundary survives when the follower holds the
    boundary entry with the boundary term; anything else — a boundary past its
    log, a boundary with a different term — means its log and the snapshot
    disagree, and the snapshot wins.
    """

    boundary = record.last_included_index
    boundary_term = record.last_included_term
    suffix = []
    if node.log.contains(boundary) and node.log.term_at(boundary) == boundary_term:
        suffix = [entry for entry in node.log.entries() if entry.index > boundary]
    node.log = RaftLog(entries=suffix, base_index=boundary, base_term=boundary_term)
    state_machine = KVStateMachine.from_snapshot_bytes(record.state)
    state_machine.last_applied = boundary
    node.state_machine = state_machine
    node.commit_index = boundary
    node.storage.save_snapshot(record)
    node.storage.sync()
    node.storage.save_log(node.log)
    node.storage.sync()
    return len(suffix)


def receive_snapshot_chunk(node: "Node", src: str, msg: InstallSnapshot) -> InstallSnapshotResponse:
    """Follower side (``SPEC.md`` 6.5, 6.6): buffer, insist on order, install
    on the last chunk, and answer with the offset the leader owes us.

    The answer is always the offset this node expects next, which is what
    makes a leader that sent the wrong chunk — or a chunk that arrived twice —
    correct itself without the follower having to say more.
    """

    pending = node.pending_installs.get(src)
    if (pending is None or pending.last_included_index != msg.last_included_index
            or pending.last_included_term != msg.last_included_term):
        pending = PendingInstall(leader_id=src, last_included_index=msg.last_included_index,
                                 last_included_term=msg.last_included_term, received=bytearray())
        node.pending_installs[src] = pending
    if msg.offset != pending.next_offset:
        return _install_response(node, pending.next_offset)

    pending.received.extend(msg.data)
    pending.next_offset = msg.offset + len(msg.data)
    if not msg.done:
        return _install_response(node, pending.next_offset)

    record = SnapshotRecord(
        last_included_index=msg.last_included_index,
        last_included_term=msg.last_included_term,
        state=bytes(pending.received),
        config=tuple(node.config.sorted_voters()),
    )
    kept = _install(node, record)
    node.pending_installs.pop(src, None)
    node.trace.record(node.global_tick, node.node_id, "snapshot_installed",
                      last_included_index=record.last_included_index,
                      last_included_term=record.last_included_term,
                      kept=kept)
    return _install_response(node, pending.next_offset, done=True)


def on_snapshot_ack(node: "Node", src: str, msg: InstallSnapshotResponse) -> None:
    """Leader side (``SPEC.md`` 6.4): follow the follower's offset, and when it
    says it is done, put it back on the ``AppendEntries`` path."""

    transfer = node.snapshot_transfers.get(src)
    if transfer is None:
        return None
    transfer.offset = msg.offset
    if not msg.done:
        send_snapshot_chunk(node, src, offset=msg.offset)
        return None
    transfer.done = True
    node.snapshot_transfers.pop(src, None)
    boundary = transfer.record.last_included_index
    node.match_index[src] = max(node.match_index.get(src, 0), boundary)
    node.next_index[src] = boundary + 1
    node._send_append(src)
    return None

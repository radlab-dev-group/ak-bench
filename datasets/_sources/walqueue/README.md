# WALQueue

A single-writer durable queue built on Python 3.12's standard library. It has
no daemon, implicit clock or third-party runtime dependency. Run the public
repository tests with `PYTHONPATH=src python -m pytest tests`. The command-line
consumer accepts JSON lines: `python -m walqueue.cli DIRECTORY`.

## Semantics

`put` creates a named task and permanent idempotency key (default: task id).
Retrying an identical put returns its task id without resurrecting completed
or dead tasks. Reusing a key for a different request raises KeyConflict. The
identity includes the original available_at and max_attempts, not subsequent
retry times. `put_many` commits its entire list as one transaction or none of
it. Payloads are JSON objects, copied at API boundaries. Task ids and keys are
never reused, including after compaction.

`reserve(worker, now=..., lease_seconds=..., limit=...)` first expires all
leases whose deadline <= now, then leases ready tasks in (available_at,
task_id) order. Each reservation increments both attempts and generation.
An expired/released task becomes ready unless attempts reached max_attempts,
in which case it becomes dead. An expired task's next available_at is its old
deadline; release uses now + delay. reserve's reap and lease transactions are
separate atomic operations. Times are explicit nonnegative integers.

ack/release require the currently leased task, worker and generation, and now
strictly less than its deadline. Reject stale operations with StaleLease and
no changes, including no journal append. Generations must survive retries,
snapshots and restarts even when the same worker reserves again. A token's
payload is informational; changing it cannot change durable task payloads.

## Storage and recovery contract

Each WAL frame is a four-byte big-endian payload length, canonical JSON, and
32-byte SHA-256 digest of that JSON. Payload length is bounded. One complete
frame is one atomic transaction, with a globally increasing sequence beginning
at 1. Applying a transaction must use exactly the same transitions during
normal operation and recovery. Never replay part of a transaction.

Only an incomplete final frame in the newest WAL segment is a recoverable
torn tail: truncate it before appending. Incomplete sealed segments, checksum
errors, invalid transactions and sequence gaps are CorruptStore errors. An
operation interrupted after its complete frame was written may be recovered
even if its caller did not see success. Operations interrupted before a full
frame must not appear. After a hook raises, discard the Queue and reopen it.

A snapshot contains the COMPLETE state through its recorded sequence:
tasks in all four statuses, attempts, generations, active lease owners and
deadlines, original idempotency identities and completed/dead tombstones.
CURRENT is an atomically replaced, checksummed pointer naming the published
snapshot and its sequence. Snapshot files without a CURRENT reference are
orphans and must never become authoritative just because their name is newer.
Loading a corrupt/missing referenced snapshot is an error, never fallback.

Compaction order is: rotate the WAL; write and sync the snapshot; publish and
sync CURRENT; delete sealed segments and sync the directory. During recovery,
load ONLY CURRENT's snapshot, skip WAL transactions with sequence <= snapshot
sequence, and replay its contiguous suffix once. Old sealed segments may still
exist after publication: they must not resurrect or double-apply old state.
No task state may be normalized away when building a snapshot. A restart must
be observationally equivalent to uninterrupted execution at every crash point.

## Fault injection

Pass `hook=callable` to Queue. The callback receives these exact phase names:

| Phase | Bytes/state already persisted |
|---|---|
| append.header | only the new frame header |
| append.payload | header and payload, without digest |
| append.frame | complete new transaction frame |
| append.synced | complete frame fsynced, before publishing in-memory state |
| compact.rotated | new empty segment; old CURRENT remains authoritative |
| compact.snapshot | snapshot synced; old CURRENT remains authoritative |
| compact.manifest | new CURRENT synced; old segments still present |
| compact.pruned | sealed segments deleted and directory synced |

Raising InjectedCrash simulates process death without sleeps or nondeterministic
threads. Crash tests model the bytes present at that phase; durability under
hardware that violates fsync is outside this project. Only one Queue may own a
directory at a time. Tests close the logical owner by discarding the object.

Preserve the API, disk format and these rules. Do not modify tests, add runtime
dependencies, special-case task ids or phase names, or bypass checksums.

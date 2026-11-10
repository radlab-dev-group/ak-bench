# ADR-0012: Persist before reply — sync points and the storage seam

Status: accepted. Referenced by: `SPEC.md` 5, `tidewater.storage.Storage`,
every `storage.sync()` call in `tidewater.node`.

## Context

Raft's safety argument assumes that when a server says something, it
remembers having said it. A voter that grants a vote and forgets can vote
again in the same term for another candidate: two leaders
(`docs/incidents/INC-0002`). A follower that acknowledges an append and
forgets lets the leader count a replica that does not exist: a committed
entry on fewer servers than a majority (`docs/incidents/INC-0003`). Both
incidents had the same root cause — a write that had been made but not
made durable when the reply left — and the same unhelpful symptom: a
safety violation hundreds of ticks later, on a different node, with no
crash in sight.

A simulator with no disk cannot fsync, but it can model the difference
between "written" and "durable", and it has to, or crash tests test
nothing.

## Decision

1. `Storage` keeps two copies of the persistent state: the **volatile**
   copy the node writes to and the **durable** copy that only `sync()`
   updates. `crash()` discards the volatile copy. This is the seam.
2. The node calls `sync()` at fixed **sync points** (`SPEC.md` 5.2):
   after adopting a higher term, after voting for itself, after granting a
   vote, after appending or truncating entries as a follower, after
   appending an entry as leader. In every case the sync comes **before**
   the message that depends on the write is placed in the outbox.
3. Three **sync policies** make the seam testable: `always` (every write
   is durable at once — the default, modelling fsync-per-write),
   `explicit` (writes become durable at `sync()` — modelling group commit,
   where the sync points are what matters) and `never` (`sync()` is a
   no-op — modelling a broken disk, so a test can show the violation).
4. `Storage` counts `write_count`, `sync_count`, `crash_count` and
   `lost_writes`, so a test can assert that a node synced before replying
   and not merely that the final state happens to be right.

## Why the sync is in the node, not in the storage

A storage that synced on every write would make the sync points invisible
and the `explicit` policy pointless. The protocol says *when* durability is
required; the node is the protocol; so the node says when. The storage only
has to make the distinction observable.

## Alternatives considered

* **Sync in the cluster loop, once per tick, before draining outboxes.**
  Simpler and coarser; it would make the ordering "sync before the reply
  leaves" true by construction. Rejected because it hides exactly the bug
  class the seam exists to expose: a node that forgets to sync would be
  indistinguishable from one that does not.
* **No seam; assume durable writes.** The prototype. See incidents.
* **A write-ahead log file on disk.** Faithful and slow, and the
  simulator's point is to run thousands of ticks in a second.

## Consequences

* `tests/test_cluster.py::test_durable_follower_keeps_committed_entries_across_restart`
  and `..._violates_leader_completeness` are the same scenario under
  `always` and `never`: a follower that acknowledged a commit crashes and
  restarts, then the leader is cut off. With durable writes the follower
  is the only electable node; without them a node lacking the committed
  entry wins and `leader_completeness` fires.
* `tests/test_node_election.py::test_vote_is_granted_once_per_term_and_persisted_before_the_reply`
  checks the durable view, not the volatile one, right after the vote.
* The `crash` trace event records `lost_writes`, so a trace shows whether
  a crash lost anything — in a correct run under `always` or `explicit`
  it never does.
* An implementation of snapshots (ADR-0006) has two more sync points,
  record-then-log, in that order.

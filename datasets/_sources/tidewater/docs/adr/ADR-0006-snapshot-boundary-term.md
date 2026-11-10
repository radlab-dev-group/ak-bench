# ADR-0006: A snapshot records last_included_term, and the record is durable before the log is cut

Status: accepted (feature declared, not implemented). Referenced by:
`SPEC.md` 6.2–6.3, `RaftLog.compact_to`, `SnapshotRecord`,
`tidewater.snapshot.take_snapshot`.

## Context

Compaction throws away the prefix of the log. Two things that the prefix
used to answer still have to be answered afterwards:

1. **Log matching at the boundary.** A leader whose `next_index[p]` is one
   past the follower's compacted boundary sends `prev_log_index =
   boundary`. The follower no longer has that entry. If it cannot say what
   term the boundary entry had, it cannot run the check in `SPEC.md` 3.2
   and must either reject (forcing a snapshot transfer that is not needed)
   or accept blindly (unsafe).
2. **Election up-to-dateness.** A node whose log is entirely compacted has
   no last entry. Its `last_log_term` for `RequestVote` has to come from
   somewhere.

Separately, the order of "write snapshot" and "cut log" matters for
crashes. A node that cuts first and crashes before the snapshot is durable
restarts with neither the entries nor the state that summarised them. That
node has lost committed entries, which is the one thing the persistence
contract forbids.

## Decision

1. The snapshot record carries `last_included_index` **and**
   `last_included_term`. The log keeps them as `base_index`/`base_term`
   after compaction, and `RaftLog.term_at(base_index)` returns
   `base_term`, so `matches(base_index, base_term)` is true and `last_term`
   of an empty compacted log is `base_term`.
2. The order of effects in `take_snapshot` is fixed: build the record;
   save and sync it; compact the log; save and sync the log. A crash
   between the two syncs leaves a longer log and a usable snapshot. The
   seed's `RaftLog.compact_to` already refuses a boundary whose term does
   not match the log, so the record cannot be built from a stale term.
3. The record also carries the configuration in force at the boundary
   (`config`), because a node restoring from a snapshot with a fully
   compacted log has no config entries left to derive it from
   (`SPEC.md` 7.1).

## Alternatives considered

* **Keep the boundary entry itself in the log** (compact to `index - 1`).
  Equivalent in effect; rejected because it makes "the log is empty" an
  impossible state and every length computation has an off-by-one.
* **Let the leader fall back to a snapshot transfer whenever the boundary
  is involved.** Rejected: every follower would receive a full snapshot
  after every compaction, which is the cost compaction exists to avoid.
* **Cut the log first, under the assumption that snapshots are rare.**
  Rejected for the crash reason above; rarity is not a safety argument.

## Consequences

* The seed never compacts, but `RaftLog` is already written for a non-zero
  base: `first_index`, `term_at`, `matches`, `slice` and `truncate_from`
  all respect it, and `tests/test_log.py::test_truncate_refuses_compacted_prefix_and_compact_keeps_boundary_term`
  pins the behaviour at the boundary.
* `SnapshotRecord` is part of `PersistentState` now, so introducing
  snapshots does not change the storage format.
* An implementation that writes the record after cutting the log will pass
  every test that does not crash between the two steps. The acceptance
  tests for the feature crash there on purpose (`SPEC.md` 6.2, 6.6).

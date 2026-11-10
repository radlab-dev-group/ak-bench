# ADR-0011: Snapshot transfer resumes from the follower's offset; partial installs are volatile

Status: accepted (feature declared, not implemented). Referenced by:
`SPEC.md` 6.4–6.6, `InstallSnapshot`, `InstallSnapshotResponse`,
`tidewater.snapshot.SnapshotTransfer`, `PendingInstall`.

## Context

A snapshot is shipped in chunks because a single message carrying the
whole state would make `max_delay` meaningless and because real systems
do it that way. Chunking creates two questions the single-message design
does not have: who owns the transfer position, and what happens to a
half-received snapshot when somebody crashes.

The prototype's answer to the first was "the leader": it kept an offset per
follower and advanced it on each acknowledgement. The prototype's answer
to the second was "nothing special": a follower wrote chunks to its
durable state as they arrived. Both answers failed together in one
scenario. A follower crashed after acknowledging chunk 3 of 5 and
restarted with chunks 1–3 on disk; the leader, which had meanwhile also
crashed and restarted, was no longer leader; the new leader began a new
transfer from offset 0 of *its* snapshot, which was taken at a different
index; the follower appended the new leader's chunk 1 after its old chunk
3, acknowledged offset 4 × chunk, and installed a state that was the first
three fifths of one snapshot and the last two fifths of another. The state
digest was garbage and `state_machine_safety` fired — eventually, once a
client read the key that straddled the seam.

## Decision

1. **The follower owns the position.** Every `InstallSnapshotResponse`
   carries `offset = the next byte the follower expects`. The leader sends
   the chunk at that offset, whatever its own counter says. A follower
   that receives a chunk at an unexpected offset replies with its expected
   offset and otherwise ignores the chunk.
2. **Partial installs are volatile.** Chunks are buffered in memory
   (`PendingInstall`). Only the complete, verified record is saved and
   synced — before the `done = True` acknowledgement, not after. A follower
   that restarts mid-transfer has no buffer and answers the next chunk with
   `offset = 0`, which restarts the transfer from the leader's current
   snapshot.
3. **A transfer is pinned to one record.** The leader's `SnapshotTransfer`
   keeps a reference to the `SnapshotRecord` it started with; a newer
   snapshot taken mid-transfer does not switch the byte stream. The
   follower checks `last_included_index`/`last_included_term` on every
   chunk and treats a change as a new transfer (reset to offset 0).
4. **The leader's state is also volatile.** A restarted leader is not a
   leader; the new leader starts fresh. There is nothing to resume on the
   leader side, by design.

## Alternatives considered

* **Make partial chunks durable with a transfer id.** Resumable across
  follower crashes, which saves bandwidth, at the cost of a durable format
  for partial snapshots, a transfer identity that both sides must agree on,
  and cleanup of abandoned partials. Rejected: the simulator's snapshots
  are small and the complexity is exactly where bugs live.
* **Leader-owned offset with a follower-side check.** The follower still
  needs to say what it expects; once it does, the leader's counter is
  redundant.
* **Single-message snapshots.** Rejected; see context.

## Consequences

* `InstallSnapshotResponse.offset` exists in the seed's message set with
  this meaning, so the wire format does not change when the feature lands.
* The acceptance tests for the feature crash a follower between chunks
  and crash the leader between chunks (`SPEC.md` 6.6); an implementation
  that persists partial chunks or trusts its own counter fails them.
* A chunk that is duplicated by the network (`dup_rate`) arrives at an
  offset the follower has passed; it is answered with the expected offset
  and the leader, which may have already sent the next chunk, simply
  continues. Duplicates cost one extra message, never a wrong install.
* The `done` acknowledgement is the only point at which the leader updates
  `match_index` and `next_index` for the follower
  (`SPEC.md` 6.5); until then the follower is treated as having matched
  nothing.

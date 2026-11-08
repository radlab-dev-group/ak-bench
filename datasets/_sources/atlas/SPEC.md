# Atlas specification

Normative. `README.md` is a map; this is the contract. Every rule below is
implemented, except section 9, which declares a feature that is not.

## 1. Identity and time

1.1 A **record** is one immutable version of one key. It carries a `key`, a
`value`, a `generation`, a version `vector`, a `deleted` flag, an `lsn`, a
`written_at` in milliseconds, and the `writer` that produced it.

1.2 The **generation** is a per-key counter owned by the primary replica,
starting at 1 for the first write and increasing by exactly 1 per accepted
write, including deletes.

1.3 The **LSN** is drawn from one monotonic counter per shard. It never
regresses and never repeats within a shard, and it is the store's only
"after".

1.4 A **tombstone** is the record a delete leaves behind. It is a value, not
an absence: it occupies the key, carries a generation and an LSN, and is only
removed by retention after the grace period. A read never returns a tombstone;
`resolve` does.

## 2. Placement

2.1 A key's **shard** is `hash(key) % shard_count`: a pure function of the
key and the shard count. It does not depend on membership, plans, or epochs.

2.2 A key's **owner** is decided by the ring in `atlas.ring`: the first
virtual node at or after the key's position, **wrapping to the first virtual
node** when the key sorts past the last.

2.3 A **plan** is a ring plus the epoch it was built under, and it is
immutable. The cluster holds one current plan.

2.4 The owner of a key is asked of the **current plan at the moment of the
write**. Holding a plan across a publication and asking it afterwards is a
stale answer, and a stale answer is not an error — it is a write to a replica
that no longer holds the key.

2.5 `atlas.compat.legacy_shard_for` and `atlas.vendor.ring` answer a
different, v1 question. They are never consulted by the write or read path,
and "fixing" them changes no store behaviour.

## 3. Durability

3.1 A transaction is a `BEGIN` frame, zero or more `PUT`/`DELETE` frames, and
a `COMMIT` frame. **It is durable exactly when its `COMMIT` frame is durable.**

3.2 A replay discards an unterminated transaction and applies every record of
a committed one exactly once.

3.3 **Torn-tail repair** cuts a segment back to the end of the last frame that
decoded cleanly, and nothing earlier. Frames before the damage include
committed transactions; a committed transaction is never collateral damage.

3.4 A frame's checksum covers the magic, kind, length and payload. A truncated
tail therefore cannot present a valid checksum for the bytes it received.

## 4. Snapshots and the boundary

4.1 Writing a snapshot file does not publish it. **The `CURRENT` pointer is
the publication decision**, and it is updated atomically.

4.2 Recovery reads `CURRENT`, restores the memtable to that snapshot, and
then applies the log. A snapshot file that `CURRENT` does not name is ignored,
including when it is newer.

4.3 A snapshot at `last_lsn = N` **already contains** record `N`. Recovery
therefore applies records with `lsn > N`. The convention is the configuration
key `compaction_lsn_boundary`, default `exclusive`, and `atlas.clock` is the
only place it is spelled.

4.4 Re-applying a record a snapshot already contains is a defect, not a
no-op: the values this store keeps include plain counters, and a doubled
increment is a wrong answer no checksum can see.

## 5. Fencing

5.1 The **generation check** compares the generation a caller offered with
the generation the store holds. Under `generation_check = strict` they must be
**equal**; a mismatch in either direction is refused. Under `permissive` a
smaller offer is accepted (a peer catching up) and a larger one is still
refused (the primary has been bypassed).

5.2 The **epoch check** compares the epoch a write was planned under with the
cluster's epoch. They must be equal. There is no permissive epoch: a node
cut off and returned is not racing, it is gone.

5.3 The epoch check runs **before** the generation check.

5.4 A **commit marker** (`Atlas.acknowledge`) carries a generation and is
checked exactly as a write is. Acknowledging a generation that is no longer
current is refused, because it asserts that work a replacement has since
redone was finished by the old holder.

5.5 An aborted transaction releases the leases it held. A transaction that
will never commit must not keep a key unwritable.

## 6. Replication and convergence

6.1 A write is acknowledged by the replicas the current plan names, and
succeeds when at least `write_consistency` of them hold it durably. A read
needs `read_consistency` **answers**, and "no such key" is an answer.

6.2 `read_consistency + write_consistency > replication_factor` is required at
configuration time. Without it the store is not a quorum store and the read
path cannot compensate.

6.3 When replicas disagree the winner is the version that **dominates
causally**. When neither dominates — concurrent writes — the winner is the one
whose **greatest writer identifier is largest** (`tie_break = desc-writer`).
Every replica must reach the same winner; a tie-break that differs between
replicas makes the divergence permanent.

6.4 Repair writes the winner forward to the replicas that lack it. It never
writes a loser and never merges values.

6.5 A digest in `atlas.antientropy` covers key, generation and LSN — **not the
value**. Two replicas with equal digests agree on versions, not on content.

## 7. Rebalancing

7.1 The sequence is: build the plan, compute the movement, stream and catch
the destination up, publish the plan, release the source. Only that order.

7.2 Publishing before the stream routes writes to a replica that does not
hold the key; releasing before the stream loses it. Neither is visible in one
write, both are visible after a rebalance.

7.3 A migration copies records, tombstones included. Dropping tombstones from
a copy is how a deleted key comes back.

7.4 A migration checkpoint records its phase (`planned`, `streaming`,
`caught_up`, `released`, `done`) and the highest LSN copied; a resumed
migration does not recopy and does not skip.

7.5 A rebalance advances the membership epoch. Writes admitted under the
previous epoch are refused by §5.2, not quietly rerouted.

## 8. Configuration

8.1 Precedence, lowest to highest: defaults, file, profile, environment,
explicit overrides. A profile beats the file and loses to the environment.

8.2 A layer contributes a key only when it names it. An empty string is a
value, not an absence, and is validated as one.

8.3 `read + write > replication_factor` (§6.2) is enforced here, not at first
use.

## 9. Lineage — declared, not implemented

This is the specification of a feature whose code raises
`NotImplementedError`. Implement it against this text.

9.1 **What it records.** Lineage is a directed graph. A **node** is a key at a
generation on a replica. An **edge** says that one node exists because of
another. Exactly five edge kinds exist and no sixth may be invented:

| kind | the cause is |
| --- | --- |
| `caused_by` | a write that read a prior generation of the same key |
| `replicated_by` | a quorum write that landed on a second replica |
| `repaired_by` | repair or anti-entropy wrote a peer's version forward |
| `migrated_by` | a rebalance moved the record to another replica |
| `restored_by` | recovery applied the record from the log after a restart |

9.2 **Idempotence.** An edge is identified by `(parent, child, kind)`.
Recording the same edge twice is one edge: a replay of a log that already
produced lineage must not double it, and `LineageGraph.add` returns `False`
for a duplicate.

9.3 **Roots.** A write with no generation offered — nothing was read — is a
root: it records no `caused_by` edge and its trace has length one.

9.4 **Derivation.** The store calls `LineageRecorder.record_write(key, record,
author=..., cause=...)` on every accepted write and passes the version the
writer read as `cause`, or `None`. The recorder derives the edge; the store
does not construct edges.

9.5 **Direction.** `why(key, generation)` returns the edges whose **child** is
that version — the causes. `whence(key, generation)` returns the edges whose
**parent** is that version — the effects. They must stay consistent with each
other: an edge appears in exactly one `why` and exactly one `whence` per
endpoint.

9.6 **Ordering.** `trace(key, generation)` walks causes, oldest first, with no
node repeated, and terminates on a cycle rather than looping. `history(key)`
returns every edge mentioning the key in the order it was recorded.
`export()` orders by LSN then by node identity.

9.7 **Completeness.** A version reachable from a recorded write by `trace`
must be present in the graph. A cause the recorder was never told about is not
a violation; a cause it was told about and dropped is.

9.8 **Off switch.** With `lineage_enabled = false` the store must not call the
recorder, and no other behaviour may change: lineage is an observer, never a
participant in the write path.

9.9 **Independence.** The recorder reads no storage. It is given facts and
draws a graph. A bug in lineage must not be able to change what the store
writes, reads, repairs or recovers.

9.10 **Cap.** At `max_edges` the recorder stops recording and says so by
returning `None`; it never evicts an edge already in the graph, because an
edge that disappears silently is worse than a graph that stops growing.

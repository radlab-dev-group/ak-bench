# ADR-0003: A version is minted once, at admission, and moved unchanged

Status: accepted. Refines SPEC.md §5.1, §5.4, §6.4.

## Context

A record's version is its generation and its vector. Both are assigned when a
write is admitted — the generation by the replica's own counter, the vector
by incrementing the writer's entry — and that is the only time either is
assigned. Everything that moves a record afterwards (read repair, a
convergence pass, a migration during rebalance, replay after a restart)
copies the record as it is.

Two incidents broke this from opposite ends. In the first, repair brought a
lagging replica level by writing the winner forward *one generation ahead*,
so that it would dominate whatever the replica had held; after one read the
repaired replica was ahead of the others, the next read moved the others
past it, and the next write was refused by the fence with *offered generation
3 but the current generation is 2*. The fence was blamed; the fence was
right. In the second, the lease book was changed to follow whatever
generation a commit reported, "so that a replica that was behind does not
leave the key unwritable"; a worker that had missed a write then committed at
a generation already on record, took the lease sideways, and the lease named
a version the store had moved past.

Relaxing the fence to accept the repaired generation silences the first and
reintroduces the second; tightening repair to go through the fence's own
checks turns the second into the first. Neither is the rule.

## Symptom

Either of:

* after one read of a key, the replicas disagree about its generation, the
  disagreement moves rather than closes on the next read, and the next write
  is refused with *offered generation N+1 but the current generation is N*;
* a commit at a generation **at or below** the one the lease records is
  accepted, and `generation_at(key)` afterwards differs from the generation
  the store holds.

## Decision

* A version is minted exactly once, by the admitted write. Repair, anti-
  entropy and migration carry the winner's generation and vector unchanged
  and write it under the reconciling path, which orders by vector; they
  never call the write path and never advance anything.
* The lease book records the generation the admitted write produced and
  moves **forward only**. A holder offering a generation at or below the one
  on record is refused with the stale-generation error, whichever path it
  arrived by.
* When the generation in storage and the generation on the lease disagree,
  the defect is in whatever moved the record, not in the check that noticed.

## Consequences

* After a repair, every replica the plan names holds the same (generation,
  vector), and a second read repairs nothing.
* A write whose first acknowledgment comes from a replica that is behind is
  refused by the lease; the replica must be brought level by a read first.
  This is a sharp edge, documented here rather than smoothed over, because
  the alternative is a lease that lies.
* Fencing's generation check stays an equality under `strict`, as README.md
  rule 4 says; this record does not relax it and no incident note may.

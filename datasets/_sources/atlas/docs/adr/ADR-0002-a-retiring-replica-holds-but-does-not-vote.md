# ADR-0002: A retiring replica holds data and does not vote

Status: accepted. Refines SPEC.md §6.1 and §7.1; SPEC.md does not yet mention
retirement.

## Context

Retiring a replica is a window, not an instant: between the operator's
decision and the rebalance that moves the keys away, the replica is still
named by the current plan and still holds every byte it held before. Two
incidents put that window on opposite sides of the same question. In one, a
write was reported committed with one healthy copy and one copy on the
replica being retired; the retirement finished, the healthy copy's node was
restarted, and the write was gone. In the other, a convergence pass run
during a retirement reported that the shard would not converge, because the
pass had left the retiring replica out of its participants while the plan
still named it, and the rebalance that followed streamed the stale copy
onto the new primary.

The fixes proposed for each were the same one-line change with the sign
flipped: count the retiring replica everywhere, or count it nowhere. Either
change makes one symptom disappear and the other reappear with the same
error, which is how the two incidents were open at the same time for a day.

## Symptom

Either of:

* a write is reported committed although fewer than `write_consistency`
  healthy replicas hold it, and a read after the retirement cannot find it;
* a convergence pass raises *shard N did not converge for epoch E*, naming a
  key that the replica being retired holds at an older version, and a
  rebalance away from that replica afterwards moves the older version.

## Decision

The set of replicas that **hold** a key and the set of replicas whose
acknowledgment **counts toward a quorum** are two different sets, and a
retiring replica is in the first and not in the second.

* It holds: every write the plan routes to it still lands on it; every
  repair and every convergence pass still compares it and brings it level;
  every rebalance still streams from it. The plan names it until the plan
  does not.
* It does not vote: its acknowledgment of a write does not count toward
  `write_consistency`, and its answer to a read does not count toward
  `read_consistency`. A quorum is a promise about what can be found again
  later, and a replica that is leaving cannot make that promise.

A pass that checks whether a shard has converged checks it against **the
replicas the plan names**, not against the list it chose to repair, because
the plan is what the rebalance will read.

## Consequences

* Retiring one replica of three with `R = W = 2` keeps the cluster writable
  and readable. Retiring two of three makes it neither, loudly, with the
  quorum error that names the epoch; that is the intended refusal, not an
  outage to be fixed by counting the leaving replicas.
* The two sets are computed in one place and asked for by name. Code that
  wants "which replicas" must say which of the two it means.
* The shortfall message reads *acks below quorum for epoch E*; the count in
  it is of votes, never of copies.

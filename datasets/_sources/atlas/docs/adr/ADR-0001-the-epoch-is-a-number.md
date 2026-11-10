# ADR-0001: The epoch is a number, and the comparison is less-than

Status: accepted. Supersedes nothing. Referenced by SPEC.md §1 and §5.2.

## Context

Early clusters carried a "settling window" after a membership change: a
write planned under epoch `E` was accepted for a few seconds after the
cluster moved to `E+1`, on the theory that the writer had simply not heard
yet. The window was a clock, and a clock is the one thing the store promised
it would never compare. In two incidents a node that had been cut off for
minutes, not seconds, committed inside the window because its own clock had
stopped with it.

## Symptom

A write admitted before a rebalance lands after it, on a replica the new plan
does not name for that key, and the next read does not see it. No error is
raised anywhere; the write "succeeded".

## Decision

An epoch is an integer. Epoch `E` is stale the moment the cluster has `E+1`.
There is no grace period, no window, and no clock. Fencing compares the epoch
a write was planned under with the epoch the membership holds, and refuses on
inequality; a replica at `E-1` is not "close enough".

The epoch is carried **on the write** and re-checked **at commit**, not at
admission, because commit is where a cut-off node comes back.

## Consequences

* A rebalance advances the epoch and the old epoch's writes are refused by
  the fence, not rerouted (SPEC.md §7.5).
* A node that returns after a partition must re-plan every write it holds; it
  cannot replay them.
* Error messages that mention a quorum, a convergence pass or a refusal carry
  the epoch they were evaluated under, because the same count means different
  things under different memberships.

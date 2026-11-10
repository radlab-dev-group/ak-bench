---
id: INC-1201
severity: high
module: membership
tags: quorum, drain, ops
---

# INC-1201: a write that two replicas held and one could keep

## What we saw

During a routine retirement of `atlas-2`, a write to a key on shard 1 came
back committed. Two replicas had it: `atlas-0`, and `atlas-2`, which was the
one being retired. `atlas-1` was mid-restart. The retirement finished, the
plan stopped naming `atlas-2`, `atlas-0` was restarted for an unrelated
kernel update, and the key read as its previous value from every replica the
plan named. The repository suite was green throughout.

## What it turned out to be

The membership did not mark the node as leaving in a way the write path could
see, so the write path counted its acknowledgment like any other. Two
acknowledgments is the configured write quorum, so the write was committed
on paper. We changed the membership record for the node during the drain and
the symptom went away in staging; it is in the archive because the same
symptom came back in INC-1203 with a different note attached.

## What we changed

Operators now drain one replica at a time and wait for the convergence pass
before the rebalance. The runbook says why in one line: a replica that is
leaving is not a vote you can collect later.

## Read next

INC-1203 for the convergence side of the same week, and the decision record
that settles both, which is written about the symptom and not about the
module this note names.

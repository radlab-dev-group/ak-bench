---
id: INC-1203
severity: high
module: rebalance
tags: anti-entropy, drain, convergence
---

# INC-1203: the pass that would not converge during a drain

## What we saw

With `atlas-1` marked as leaving and a rebalance scheduled, the pre-rebalance
convergence pass stopped with *shard 0 did not converge for epoch 1*, naming
a key that `atlas-1` held one generation behind the other two. Running the
pass again gave the same answer. Skipping the pass and running the rebalance
moved the old generation onto the new primary, from `atlas-1`, which the plan
still named as the key's owner.

## What it turned out to be

The rebalance was the first suspect, since it was the thing that did the
damage, and this note was filed against it. The rebalance did what it was
told: it streamed from the replica the plan named. The pass had left the
leaving replica out of the set it compared and repaired, on the reasoning
that traffic spent on a replica that is leaving is spent twice; the check at
the end of the pass still read the plan, found the stale copy, and said so.
The rebalance then read the plan too.

## What we changed

The pass compares and repairs every replica the plan names, leaving or not,
and the check at the end keeps reading the plan. The one-line change proposed
at the time — to make the check read the same shortened list, so the pass
would report clean — would have made the rebalance move the stale copy
silently, and was not applied.

## Read next

INC-1201. The two are one incident seen from two sides, and the rule that
resolves both is in one decision record.

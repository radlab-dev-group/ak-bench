---
id: INC-2906
severity: high
module: convergence
kind: the rule behind a rule
tags: protocol, read-first
---

# INC-2906: the winner is the name not the hour

Two writers, neither seeing the other, one row. The tie is not broken by
timestamp, and it is not broken by who wrote last in wall-clock order, and it
is not broken by which replica noticed first. It is broken by the name of the
writer, and the greatest name wins, and every replica must reach that same
answer or repair makes the disagreement permanent instead of curing it. We
changed the direction of this comparison once, on a branch, in one module, and
the cluster spent a week in a state where two replicas each confidently
repaired the other back to its own version. Whichever direction it is, it is
one direction, in one place.

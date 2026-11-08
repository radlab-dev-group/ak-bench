---
id: INC-2904
severity: high
module: placement
kind: the rule behind a rule
tags: protocol, read-first
---

# INC-2904: two halves of one decision

Which partition a key lives in, and which machine is allowed to answer for
it, are different questions, and this cluster asks them of different places.
The first depends on the key and nothing else. The second depends on the plan
of the moment, and a plan is a snapshot of a decision that has since been
remade. The incident was a rebalance where a caller asked the second question
of a plan it had carried across the switch, and the answer was a machine that
no longer held the key. Nothing raised. A write went somewhere, and later a
read did not find it.

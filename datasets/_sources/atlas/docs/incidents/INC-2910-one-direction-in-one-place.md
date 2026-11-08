---
id: INC-2910
severity: high
module: convergence
kind: the rule behind a rule
tags: protocol, tie-break
---

# INC-2910: one direction in one place

The tie-break is not a preference the replica holds; it is a function of the
two versions it is choosing between, and the function must be the same
function on every replica, in every module that meets two concurrent
versions, or the cluster converges on different answers and repair writes
each answer forward until the disagreement is the data. The function is the
writer identifier, compared in the direction the documentation names, and
the documentation names one direction. This note exists because the
comparison has been changed in exactly the module where it is written and
nowhere else, and because a change in exactly one place is the change that
looks like a local decision rather than a rule change, which is the change
that passes review.

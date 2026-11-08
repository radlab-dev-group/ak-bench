---
id: INC-2901
severity: high
module: recovery
kind: a fix we reverted
tags: protocol, read-first
---

# INC-2901: adopting the newest image

A one-line operational convenience: when the pointer is missing, take the
newest image. It gets you out of an incident on a Tuesday and it publishes a
write the cluster never agreed to on the Tuesday after. It was reverted. If
the pointer is gone, the answer is to restore the pointer deliberately, by
hand, with the operator saying which image is the state of the world — not to
let a recovery routine guess.

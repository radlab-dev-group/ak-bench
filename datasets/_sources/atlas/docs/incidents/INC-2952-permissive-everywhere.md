---
id: INC-2902
severity: high
module: fencing
kind: a fix we reverted
tags: protocol, read-first
---

# INC-2902: permissive everywhere

`generation_check = permissive` exists for one migration in which a peer is
behind. Someone set it cluster-wide to stop an alert, and the alert stopped
because the writes it was reporting were now accepted. A permissive check is
a narrower door, not an open one: a caller ahead of the store is refused even
in permissive mode, and a caller from a finished epoch is refused in every
mode. The setting that stops the noise is usually the one that names the peer
that is behind, not the one that stops asking.

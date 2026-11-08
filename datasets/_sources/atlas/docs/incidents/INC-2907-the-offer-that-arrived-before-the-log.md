---
id: INC-2907
severity: high
module: fencing
kind: a fix we reverted
tags: protocol, read-first
---

# INC-2907: the offer that arrived before the log

During one migration a peer caught up to the store a few writes ahead of its
acknowledgment path, and its offers arrived before the store's own log had
recorded what it was offering. The check refused every one of them, the peer
sat down, and the migration stalled for an afternoon. The fix we shipped was
to let an offer through when it is *ahead* of the number the store holds,
on the theory that a caller ahead of the store has seen work the store has
not yet written down, and refusing it would strand a caught-up peer. The
stall went away, and so did the meaning of the check: a number the store has
not recorded is not a number the store has endorsed, and the store is not the
peer's queue. The change was reverted in the release after, and the note
that should be read first is the one that says the strict check is an
equality in both directions, which is the rule this migration ran into
rather than the rule it should have bent.

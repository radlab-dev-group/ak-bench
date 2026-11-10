---
id: INC-1204
severity: medium
module: fencing
tags: fencing, lease, stale-worker
---

# INC-1204: a lease that walked backwards

## What we saw

A worker that had been cut off during a write came back and committed the
write it was holding. Its commit named generation 2; the lease already named
generation 2, granted to a different worker for a different value. The
commit was accepted. The lease now named the returning worker at
generation 2, while two of three replicas held generation 3. The next
ordinary write was refused, and `generation_at(key)` disagreed with the
generation every replica reported.

## What it turned out to be

The lease book had been changed to record whatever generation a commit
reported, so that a replica that had fallen behind "would not leave the key
unwritable". The forward-only check was the thing that had been protecting
the key; without it the book followed a stale worker sideways. The write
path's own refusal a moment later was correct and was the only reason anyone
looked.

## What we changed

The forward-only check was restored: a holder offering a generation at or
below the one on record is refused with the stale-generation error, and the
lease keeps its holder and its generation. A replica that is behind is
brought level by a read, which repairs it, not by a lease that lies for it.

## Read next

INC-1202, which is the same rule broken from the other end.

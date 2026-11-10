---
id: INC-1202
severity: medium
module: fencing
kind: a fix we reverted
tags: fencing, repair, read-first
---

# INC-1202: the fence refused a generation nobody wrote

## What we saw

A replica came back from a partition one generation behind on a hot key. One
read later it was one generation *ahead* of the other two. The next read
moved the other two past it. The next write was refused: *offered generation
3 but the current generation is 2*. The operator on duty read the message,
opened the fencing code, and relaxed the strict check so that an offer ahead
of the lease would pass — which it then did, while the replicas kept leap-
frogging each other on every read.

## What it turned out to be

Not the fence. The fence was the only component that noticed. The repair
path wrote the winner forward one generation ahead of itself "so that it
would dominate", and the fence refused the result because the lease had
recorded what was actually admitted. The relaxed check was reverted the
same day; see INC-2952 for what a relaxed check does to a cluster.

## What we changed

The relaxation was reverted. A lease that disagrees with storage is treated
as evidence against whatever moved the record, and the check that found it
is left alone.

## Read next

The decision record about versions being minted once. INC-1204 for the
mirror image of this incident, in which the lease was the thing that moved.

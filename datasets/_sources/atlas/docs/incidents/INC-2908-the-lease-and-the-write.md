---
id: INC-2908
severity: medium
module: fencing
kind: a near miss
tags: protocol, lease
---

# INC-2908: the lease and the write

A stale worker that had been paused through a failover came back and took
over the lease for a key it had held before, and the takeover was refused
because the holder it named offered a generation at or below the one on
record. That refusal is the lease doing its job, and it is easy to read as
the write path being too strict in the same breath, because both refusals
come out of the same module and both name the same error. They are two
checks with two different jobs: the lease check decides who may hold a key,
and the write check decides whether an offer matches what the store holds,
and the second one is an equality. When a deployment reports "fencing is
refusing a good writer", the first question is which of the two refused,
and the answer changes what is wrong. A fix for the lease direction does
nothing for the write direction, and the two have been patched against
each other twice.

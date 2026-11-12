---
id: INC-0010
severity: availability
module: node
tags: clock, skew, election, ops, capture
---

# INC-0010: A node that stopped taking part in elections after tick 1200

**Captured run:** `docs/incidents/captures/INC-0010/incident_trace.jsonl.gz` (3000 ticks, five nodes,
16 243 events, seed 20261113). Decompress it with `gunzip -c`; it is one JSON
object per line with `tick`, `seq`, `node`, `kind` and `fields`.

**Reported symptom.** The run itself finishes: 241 proposals accepted, nothing
pending, no safety violation. The operators' complaint is about what happened
after tick 1200 on the side of the cluster that contained `n3`. A leader was
elected at tick 1 for the whole run, but when `n4` was taken out for maintenance
at 1340 the side that still held a majority — `n3`, `n4`, `n5` — took far longer
than `election_timeout` to elect anyone, and the writes queued behind the
maintenance window sat uncommitted for minutes. Nothing logged an error.

**What was already ruled out.**

- Not a partition: the `heal` at tick 1180 restored every link, and the
  `send`/`deliver` events after 1200 show `n3` reaching all four peers.
- Not the lease: pre-votes from `n3` are granted after 1200, not denied.
- Not storage: no `crash` or `restart` event involves `n3`.

**The one anomaly in the trace.** There is an action at tick 1199 that changes
`n3`'s clock. Read the event, then read what `n3` does for the next few hundred
ticks — its `timeout` events, if you look for them, are the interesting part,
because there is a suspiciously long stretch without any.

`docs/schedule-spec.md` documents the action, `ADR-0002` states what a node
clock is allowed to do when its skew changes, and `SPEC.md` 2.3 states the timer
rule the consequence follows from. `docs/incidents/INC-0007` is the earlier
incident about a node whose clock did not agree with everyone else's; this one is
its cousin, and the difference between the two is what the fix has to get right.

**What is wanted.**

1. The tick at which `n3` first behaves differently from what the rules say,
   with the events that prove it.
2. The cause, in the code, and a fix that keeps a skew action able to make a
   clock run fast (`rate`) and able to declare an `offset`, without the node
   losing the time it has already counted.
3. A reproducer in `tests/test_incident_reproduction.py`, under 100 ticks and
   under two seconds, that fails before the fix and passes after it.

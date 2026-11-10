# INC-0001: Election storm after a partition heals

Severity: availability. Schedule: an ancestor of `partition-heal-storm`.
Status: closed; rules in `SPEC.md` 2.3, 2.4, 2.7; decisions ADR-0002,
ADR-0003, ADR-0009.

## Symptom

A five-node cluster with a healthy leader was partitioned `{n1, n2} |
{n3, n4, n5}` for 260 ticks and then healed. In the 420 ticks after the
heal the trace showed:

```
0002291 t=000561 n1     election_start   last_index=19 last_term=1 term=2
0002340 t=000563 n2     election_start   last_index=19 last_term=1 term=3
0002398 t=000566 n4     step_down        reason=vote_request term=3 was=leader
0002471 t=000571 n3     election_start   last_index=24 last_term=1 term=4
0002519 t=000574 n5     election_start   last_index=24 last_term=1 term=5
...
```

Fourteen terms in 180 ticks. Every candidate was denied by someone who
had already voted in that term, timed out, and started the next term. No
proposals were committed between ticks 561 and 741. The invariant monitor
was quiet throughout — nothing unsafe happened — and the run ended with a
single leader in term 15 and every log identical.

## What we found

Three things stacked up, and fixing any one of them would have reduced the
storm; fixing all three is what the rules now say.

**The minority's terms ran ahead.** `n1` and `n2`, cut off from the
leader, timed out and started elections against each other for 260 ticks.
Each election bumped the term; by the heal they were in term 11 and 12.
Their first message after the heal — a `RequestVote` with term 12 —
deposed the leader, whose term was 1. This is the Raft paper's known
disruptive-server problem. **Rule:** a node that times out does not bump
its term; it asks first (`SPEC.md` 2.4, ADR-0003).

**The timeout window was too narrow.** The prototype drew `T ± T/4`, a
25-tick window with `T = 50`. After the leader stepped down, three
majority-side nodes whose timers had been reset by the same heartbeat drew
deadlines within 6 ticks of each other. With network delay 1–3 a candidate
needs about 6 ticks to collect votes; the next node timed out before the
first had won. **Rule:** the window is `[T, 2T)`, width `T`
(`SPEC.md` 2.3, ADR-0002).

**Nodes that had just heard from the leader voted anyway.** `n3` granted
`n1`'s pre-vote at tick 562 having received a heartbeat from `n4` at tick
559. It had no reason to think the leader was gone. **Rule:** a node denies
pre-votes within `T` local ticks of hearing from a leader (`SPEC.md` 2.7,
ADR-0009).

## How it was diagnosed

The trace made it a counting exercise. `grep election_start` gave the
term sequence and the ticks; `grep "vote .*granted=False"` gave the
reasons, which were `already_voted` in every case — the signature of a
split vote, not of a log-behind or stale-term problem. The partition and
heal events bracketed the storm exactly, which pointed at the healed
minority as the trigger.

What the trace did *not* show was why the minority's terms were high,
because the prototype did not trace pre-votes (there were none) or
`step_down` reasons. Both were added as a result.

## What changed

* Pre-vote: `Node._start_prevote`, `Node._handle_prevote_request`.
* Timeout window: `Stream.election_timeout`, `Node._reset_election_timer`.
* Lease: `Node._heard_from_leader_recently`.
* Trace: `prevote_start`, `prevote` (with `reason`), `step_down` (with
  `reason` and `was`).
* Per-node random streams (ADR-0002), because the schedule that reproduced
  this stopped reproducing it after an unrelated change to heartbeat code
  shifted the shared generator.

With all three rules `schedules/partition-heal-storm` — six partitions,
each healed — runs in three terms, and `n1`/`n2` in the first partition
record 22 `prevote_start` events and zero `election_start` events while cut
off.

## What to check if you see this again

The symptom "many `election_start` in a short window, every denial
`already_voted`" has exactly three causes in this code base: the window
(2.3), the pre-vote (2.4), the lease (2.7). Check in that order; the first
one is a one-line arithmetic change and the most common regression. If
every denial is `log_behind` instead, this is not this incident — see
INC-0004.

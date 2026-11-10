# INC-0007: A node with a fast clock kept deposing the leader

Severity: availability. Schedule: an ancestor of `clock-skew`. Status:
closed; rule in `SPEC.md` 2.7 (and 2.4); decision ADR-0009.

## Symptom

A five-node cluster with no network faults changed leader every 60–90
ticks for the whole run. Every new leader was `n2`, or the node `n2` had
just deposed getting its job back:

```
0001004 t=000266 n2     timeout          local=1064 role=follower term=3
0001005 t=000266 n2     prevote_start    last_index=29 last_term=3 proposed=4 term=3
0001031 t=000269 n2     election_start   last_index=29 last_term=3 term=4
0001052 t=000271 n4     step_down        leader='' reason=vote_request term=4 was=leader
0001060 t=000272 n2     leader           commit=29 last_index=30 noop_index=30 term=4
...
0001410 t=000341 n2     timeout          local=1364 role=leader ...
```

Note `local=1064` at `t=266`: `n2`'s clock was running four times fast. The
schedule had a `skew` action on `n2` with `rate=4` at tick 200 — the
scenario was meant to test that a fast clock is *tolerated*. Throughput
was a third of the baseline because every election cost `T + 2 delays`
during which nothing committed, and the trace was 3.5x longer than the
baseline's for the same workload.

## What we found

Pre-vote (ADR-0003) was already in place, and it was doing what it says:
`n2` asked before bumping its term. The peers *granted*. By the only rule
they had — is the candidate's log at least as up to date as mine? — `n2`
was a perfectly good candidate. It was a healthy follower with a complete
log; the only thing wrong with it was that it thought 50 ticks had passed
when 12 had. Its peers had received a heartbeat 4 ticks earlier and had
no mechanism to say "but the leader is fine".

Once `n2` was leader, its heartbeats went out every 10 of *its* ticks,
which is every 2–3 global ticks; the peers were content. Then `n2` timed
out *as leader* — a leader has no election timer, but the prototype's
tick loop did not check the role before firing it — which is the second
bug in the trace above and was fixed in passing (`Node.tick` only runs the
election timer for non-leaders).

## The rule

A node that has heard from a leader within the last `T` local ticks denies
pre-votes with reason `leader_lease` (`SPEC.md` 2.7). With `T = 50` and a
heartbeat every 10, a healthy follower's lease is always fresh, and `n2`'s
pre-votes are denied by four peers every time. `n2` keeps timing out —
its clock is still fast — and keeps being told no, at the cost of one
round of pre-vote messages per `12–25` global ticks and no term change.

The window is `T` and not something shorter for the reason in ADR-0009: a
peer should grant a pre-vote only when it has itself gone long enough
without a heartbeat to be suspicious, and `T` is the shortest time at
which its own timer could fire.

## How it was diagnosed

`grep "leader "` listed the elections; every one was `n2` or an immediate
reaction to `n2`. The `timeout` event's `local` field against the global
`t=` gave the rate at a glance (`1064 / 266 = 4`). `grep "prevote .*candidate=n2"`
showed `granted=True reason=granted` from every peer — the pre-vote was
working and the peers were agreeing, which pointed at the grant rule
rather than at the pre-vote mechanism.

## What changed

* `Node._heard_from_leader_recently` and the `leader_lease` denial reason.
* `last_leader_contact` recorded on every `AppendEntries` from a current
  leader, accepted or rejected.
* `Node.tick` checks the role before the election timer.
* `schedules/clock-skew` runs `n2` at 3x and `n5` at 4x and is expected to
  stay in one term.
* `tests/test_cluster.py::test_fast_clock_node_does_not_steal_leadership_thanks_to_prevote`.

## What to check if you see this again

Repeated `leader` events naming the same node, with `timeout` events
whose `local` is a multiple of `t`, is a fast clock. If the pre-votes
preceding each election are *granted*, the lease is not being applied:
check that `last_leader_contact` is updated on heartbeats and that the
comparison is `< T` in local ticks. If the pre-votes are *denied* and the
node still becomes leader, it is not going through pre-vote at all —
check `pre_vote` in the schedule options and `Node._on_election_timeout`.
If the elections are by different nodes each time, this is INC-0001, not
this one.

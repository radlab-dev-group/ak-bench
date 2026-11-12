# A peer that will not stop asking, and a lease that will not say no

`docs/incidents/INC-0007-fast-clock-node-kept-deposing-the-leader.md` is the
earlier version of this ticket. The shape is the same and the cause is not.

An operator reports that one peer of a healthy five-node cluster spends its time
sending pre-vote requests. Every one of them is refused — the node being asked
has a leader and its lease is fresh, which is `SPEC.md` 2.7 working exactly as
designed. The peer retries with a proposed term one higher each time: 41, 42,
43, and on, always inside the same lease window, always refused, always logged as
`leader_lease`. Nothing is elected, nothing is broken, and the cluster is fine.

Except that it is not. The refused peer is learning, on every attempt, exactly
how long the lease is: the boundary between `granted` and `leader_lease` is a
timing oracle, and a peer that walks it can map the cluster's election timing
from the outside. Worse, nothing in the simulator distinguishes "a candidate
that tried once" from "a peer that has tried forty times", so the work of
refusing it is repeated forever, and the trace of a healthy run is padded with
one peer's noise.

## What to build

A **per-peer quarantine**, with these properties — they are the requirement, and
the hidden tests are written against them:

- A peer whose pre-votes are refused by the leader lease and whose *proposed*
  term keeps strictly rising inside a single lease window is quarantined for a
  bounded time.
- While a peer is quarantined, its pre-votes are refused without consulting the
  lease, and the refusal says why: the reason recorded in the trace is
  `quarantined`.
- The quarantine belongs to the peer being asked, not to the cluster: it expires,
  it does not follow the peer to other nodes, and it never affects a peer that
  has not misbehaved.
- None of it may touch persistent state — same rule `SPEC.md` 2.4 already states
  for pre-votes.

## What must not change

This is the part that has sunk previous attempts at this problem, and it is why
the task is not "reject high terms":

- **The lease is the node's own clock.** `SPEC.md` 2.7 defines it over
  `last_leader_contact` and `election_timeout`, both local. Nothing a peer puts
  in a message — a term, a timestamp, a count — may extend, reset or replace it.
  `ADR-0009` says why the lease exists; if your fix reads the incoming term to
  decide whether the lease is fresh, you have moved the clock to the attacker.
- **A real election after a real partition still has to work.** `ADR-0003` is the
  pre-vote: it exists so that a partitioned node coming back cannot disturb a
  healthy cluster, and a partition healing is the case where terms *legitimately*
  rise fast. If your quarantine fires there, the cluster stops making progress
  and the reference digests move.
- A single anomalous pre-vote, from a peer that then stops, is a node that timed
  out once. It is not an attacker and must not be treated as one.

## Deliver

1. The change, in the source.
2. A test in `tests/test_prevote_quarantine.py` covering the quarantine firing,
   the honest case not firing, and the quarantine expiring.
3. `python -m pytest tests/` green and `python tools/reference_traces.py --check`
   green — the twelve digests are the honest-traffic regression test, and they
   have to stay byte-identical.

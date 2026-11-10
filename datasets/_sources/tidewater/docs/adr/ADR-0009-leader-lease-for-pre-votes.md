# ADR-0009: A node denies pre-votes for T local ticks after hearing from a leader

Status: accepted. Referenced by: `SPEC.md` 2.7, `Node._heard_from_leader_recently`,
`Node._handle_prevote_request`.

## Context

Pre-vote (ADR-0003) stops a partitioned node from bumping its term, but on
its own it does not stop a node from *winning* a pre-vote it should lose.
Consider `docs/incidents/INC-0007`: `n2`'s clock runs four times fast. It
times out every 12–25 global ticks, long before any heartbeat is late by
its peers' reckoning. Its log is as up to date as anyone's (it is a healthy
follower), so under the plain pre-vote rule every peer grants it a
pre-vote, it runs a real election, wins, and the previous leader steps
down. Then its heartbeats are as fast as its clock and nothing is wrong
until another node with a fast clock appears — or until a partition heals
and `n2` is on the wrong side of it.

The up-to-dateness check answers "could this node be leader?" It does not
answer "is there a reason to replace the leader we have?"

## Decision

A node records the local time of the last `AppendEntries` it processed
from a leader whose term is at least its own (`last_leader_contact`). It
denies a pre-vote with reason `leader_lease` while
`local_now - last_leader_contact < T` and it knows a `leader_id`. The
window equals `T`, the minimum election timeout: if the node has heard
from the leader more recently than any correct follower could have timed
out, the pre-candidate is not reacting to a dead leader. Leaders deny
pre-votes unconditionally (`is_leader`).

The lease applies to pre-votes only. A real `RequestVote` carries a term
the candidate has already adopted; denying it does not prevent the term
bump, so there is nothing for a lease to protect, and a lease on real votes
would delay a legitimate election after a leader crash by up to `T`.

## Why T and not the heartbeat interval or 2T

* Shorter than `T` (say `2H`) would let a node that missed two heartbeats
  to loss grant a pre-vote while its own timer would not have fired for
  another `T - 2H` ticks; it would be endorsing a judgement it has not
  itself reached.
* Longer than `T` (say `2T`) would deny pre-votes from a node whose timer
  legitimately fired at `T` while the denier's own timer, drawn near `2T`,
  had not. The cluster would then wait for the slowest timer rather than
  the fastest, which is the opposite of what randomised timeouts are for.
* `T` is exactly the threshold at which the denier would itself start to
  suspect the leader. It is the one value that makes the rule read as "I
  will not help you depose a leader I have no reason to doubt".

## Alternatives considered

* **Leader-side check-quorum.** Orthogonal; does not stop the fast node.
* **Deny pre-votes from nodes whose `last_log_term` equals ours but whose
  timing looks wrong.** There is no notion of "timing looks wrong" that a
  node can compute without a lease.
* **Ignore clock skew; declare it out of scope.** Skew is one of the five
  fault kinds in the schedule format, and INC-0007 happened.

## Consequences

* `schedules/clock-skew` runs `n2` at 3x and `n5` at 4x. With the lease the
  whole schedule stays in one term and `n2` records dozens of `timeout`
  and `prevote_start` events, every one denied with `leader_lease`.
* After a leader crash, followers' leases expire `T` ticks after the last
  heartbeat; since their own timers fire in `[T, 2T)`, the first node to
  time out finds its peers' leases just expired or expiring. Elections are
  not slowed in the common case.
* A node that is partitioned *with* the leader but away from the majority
  keeps renewing its lease and keeps denying the majority's pre-votes. This
  is correct: the majority does not need its pre-vote.
* `tests/test_node_election.py::test_prevote_is_denied_while_the_leader_lease_is_fresh`
  pins the window: denied inside `T` local ticks, granted after.
* The lease uses local time, so a fast clock also expires its lease fast.
  That is why the lease protects *other* nodes from the fast node, not the
  fast node from itself: the fast node's own pre-votes are denied by peers
  whose leases, in their own time, are fresh.

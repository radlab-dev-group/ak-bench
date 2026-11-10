# ADR-0003: Pre-vote before any term increment

Status: accepted. Supersedes: nothing (the prototype had no pre-vote).
Referenced by: `SPEC.md` 2.4, `Node._start_prevote`,
`Node._handle_prevote_request`.

## Context

A node that is cut off from the leader times out and starts an election.
In plain Raft it increments its term first. When the partition heals, its
higher term reaches the leader, which steps down; the cluster elects a new
leader — usually not the returning node, whose log is behind — and the
only effect of the whole episode is a term bump and a few hundred ticks of
unavailability. With a flapping link (`docs/incidents/INC-0001`) this
repeats every time the link flaps; with a fast clock
(`docs/incidents/INC-0007`) it repeats every `T` ticks forever.

The cluster was never unsafe in these episodes. It was useless.

## Decision

A node whose election timer fires does not increment its term. It becomes
a **pre-candidate** and asks every peer whether it *would* receive their
vote in term `current_term + 1`, sending `RequestVote(term = current_term
+ 1, pre_vote = True)`. A peer grants the pre-vote only if it would grant
the real vote *and* it has not heard from a leader recently (ADR-0009).
Nothing about the pre-vote exchange is persisted on either side. Only a
majority of granted pre-votes leads to a real election (`SPEC.md` 2.5).

A pre-candidate that receives a denial carrying a higher term adopts it
and becomes a follower; this is how a node that fell behind in terms while
partitioned learns the current term without disturbing anyone.

## Alternatives considered

* **Leader leases on real votes** (deny a real vote while a leader was
  heard from recently). Rejected: the returning node still increments its
  term, and the leader still steps down on seeing it. The disruption is the
  term increment, not the vote.
* **Check-quorum on the leader** (a leader steps down if it cannot reach a
  majority). Useful but orthogonal; it addresses a stale leader, not a
  disruptive follower. Not adopted in the seed.
* **Exponential back-off.** Addresses the storm's duration, not its cause.

## Consequences

* A partitioned node's term does not run ahead. After a heal it rejoins
  as a follower in the leader's term with its election timer reset by the
  first heartbeat. `schedules/partition-heal-storm` goes through six
  partitions in three terms; without pre-vote the same schedule used
  fourteen.
* Elections take one more round trip. The corpus schedules show leader
  election in about `T + 2 * max_delay + 6` ticks from the first timeout.
* A pre-vote carries `term + 1` but the receiver must *not* adopt it.
  `tests/test_node_election.py::test_prevote_is_denied_while_the_leader_lease_is_fresh`
  asserts the receiver's term is unchanged after granting.
* Single-voter configurations skip the pre-vote (there is nobody to ask).
* `pre_vote: false` remains a schedule option so that the storm can be
  reproduced on demand.

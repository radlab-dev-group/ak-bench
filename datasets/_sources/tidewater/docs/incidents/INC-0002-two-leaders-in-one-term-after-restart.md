# INC-0002: Two leaders in one term after a restart

Severity: safety (`election_safety`). Schedule: an ancestor of
`crash-leader-chain`. Status: closed; rule in `SPEC.md` 2.6, 5.2; decision
ADR-0012.

## Symptom

```
0004112 t=001407 -      violation        detail='term 4 has two leaders: n2 and n5' violation=election_safety
```

The run stopped at tick 1407. Reading backwards: `n5` became leader in
term 4 at tick 1402 with votes from `n3` and `n4`; `n2` had become leader
in term 4 at tick 1391 with votes from `n3` and `n1`. `n3` had voted twice
in term 4 — once for `n2` at tick 1388, once for `n5` at tick 1399.
Between those two votes, at tick 1393, `n3` had crashed and restarted.

## What we found

`n3`'s vote for `n2` was written to its volatile state and the reply was
sent. The crash at tick 1393 happened before anything made the vote
durable. On restart `n3` loaded `current_term = 4, voted_for = None` — the
term had been synced when `n3` adopted it from `n2`'s `RequestVote`, but
the vote, written a moment later in the same handler, had not. `n5`'s
`RequestVote` for term 4 then found `n3` with no recorded vote.

In the prototype, `Storage` had one copy of the state and a `sync()` that
did nothing; "durable" and "written" were the same thing, so the bug was
invisible. The incident was found only after the storage seam (ADR-0012)
was introduced with `sync_policy = "explicit"` to model group commit, at
which point the missing sync between "record vote" and "send reply" showed
up on the first crash schedule that happened to crash a voter.

## The rule

A node never sends a message that reflects persistent state it has not
synced (`SPEC.md` 5.2). For votes specifically: the vote is recorded with
`storage.set_term(term, candidate)` **and synced** before the
`RequestVoteResponse` is placed in the outbox (`SPEC.md` 2.6). The same
applies to the candidate's own vote for itself when it starts an election,
and to adopting a higher term.

## How it was diagnosed

`grep "vote .*granted=True"` for term 4 showed `n3` twice. The `crash` and
`restart` events between them, with `restart ... vote=None`, said what
had been lost. The `crash` event's `lost_writes=1` — a counter the storage
seam keeps — confirmed that a write was pending at the moment of the
crash. Without that counter the diagnosis would have required reading the
node code with the trace open; with it, the trace alone was enough.

## What changed

* `Node._handle_request_vote`: `set_term` then `sync` before the reply.
* `Node._start_election`, `Node._become_follower`: the same ordering.
* `Storage.lost_writes` and the `crash` event's `lost_writes` field.
* `tests/test_node_election.py::test_vote_is_granted_once_per_term_and_persisted_before_the_reply`
  reads `storage.durable_view().voted_for` immediately after the reply.

## What to check if you see this again

`election_safety` with a `restart` event on one of the voters between the
two `leader` events is this incident. Look at every `storage.sync()` call
in `tidewater.node` and confirm each one precedes the `outbox.append` that
depends on it; the order within a handler is the whole rule. If there is
no restart in the trace, two leaders in one term is a vote-counting bug
instead — check that votes are counted against `Configuration.has_majority`
and that a candidate ignores `RequestVoteResponse` from a different term.

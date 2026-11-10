# ADR-0002: Election timeout drawn from [T, 2T) on a per-node seeded stream

Status: accepted. Supersedes: the prototype's `T ± T/4` jitter and the
shared generator. Referenced by: `SPEC.md` 2.3, `tidewater.rng`,
`Node._reset_election_timer`.

## Context

Raft avoids split votes by randomising election timeouts. Two things about
how we did it in the prototype turned out to matter more than the fact that
we did it.

**The range.** The prototype drew `T + randint(-T/4, T/4)`. With the
default `T = 50` that is `[38, 62]`: a window of 25 ticks, in which the
heartbeat interval (10) fits only twice. In `docs/incidents/INC-0001` four
nodes timed out within 6 ticks of each other after a partition healed, no
candidate reached a majority before the next timeout, and the cluster
spent 180 ticks in elections for a 5-node cluster with no faults left.

**The generator.** The prototype had one `random.Random(seed)` for the
whole simulation. Every timeout draw on any node, and every network delay
draw, advanced the same stream. A fix to an unrelated heartbeat bug on one
node shifted every later draw on every other node, and the schedule that
reproduced INC-0001 stopped reproducing it. Reproductions that evaporate
when you touch the code are worse than none.

## Decision

1. On every reset of the election timer the node draws
   `timeout = T + stream.randrange(T)`, i.e. uniformly from the half-open
   window `[T, 2T)`. Window width equals `T`.
2. The draw comes from the node's **own** stream,
   `SeedTree(seed).stream(node_id, "election")`, derived by SHA-256 from
   the root seed and the node id. The network has its own stream. No two
   consumers share a `random.Random`.
3. Streams are created in sorted node-id order and cached, so the set of
   streams in existence does not depend on which node happened to time out
   first.

## Why [T, 2T)

The lower bound `T` is the longest silence a healthy follower tolerates; it
must exceed a few heartbeat intervals plus two network delays, which the
schedule validator enforces (`3H <= T`, `2 * max_delay < T`). The width is
what controls split votes: the probability that two nodes draw within one
network round trip `d` of each other is about `2d / width`. With width `T`
and `d <= 2 * max_delay`, that is at most `4 * max_delay / T`; the validator
keeps it under 1/2 and the corpus defaults put it near 1/8. A wider window
(say `[T, 3T)`) lowers that probability further but makes the slowest node
wait up to `3T` before any election starts, which doubles the worst-case
unavailability after a leader crash for little gain. `[T, 2T)` is the
standard choice in the Raft paper and in every production implementation
we looked at, and the incident data did not give a reason to differ.

The upper bound is exclusive so that `randrange(T)` is the exact
expression; an inclusive `2T` would need `randint(0, T)` and a reader
comparing with the spec would have an off-by-one to think about.

## Alternatives considered

* **Keep one shared stream, but reseed per tick.** Rejected: a draw's value
  then depends on how many draws preceded it within the tick, which is the
  same coupling with extra steps.
* **Deterministic, non-random staggered timeouts** (`T + 7 * node_index`).
  Rejected: trivially reproducible, but every election is won by the same
  node, which hides the class of bugs that depend on *which* node wins.
* **Exponential back-off after a failed election.** Not adopted; the
  pre-vote (ADR-0003) addressed the storm that motivated it.

## Consequences

* `tests/test_clock_rng.py::test_election_timeout_is_in_half_open_window`
  pins the window, including both ends being reachable.
* `tests/test_clock_rng.py::test_streams_are_independent_per_node` pins
  the independence.
* A draw is consumed on *every* reset, including resets caused by
  heartbeats. A follower under a live leader therefore advances its stream
  every heartbeat. This is intentional: it keeps the draw sequence a
  function of what the node observed, not of what it did.
* Changing the range, the generator, or the set of reset points changes
  every trace. Each is a digest-breaking change.

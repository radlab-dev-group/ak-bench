# INC-0008: The minority side kept committing during a partition

Severity: safety (`state_machine_safety`). Schedule: an ancestor of
`partition-minority`. Status: closed; rule in `SPEC.md` 4.2;
decision ADR-0007 (consequences).

## Symptom

Five nodes, partitioned `{n1, n2} | {n3, n4, n5}` with the leader `n1` on
the minority side. The majority side elected `n4` in term 2 and committed
20 writes. The minority side — two nodes — *also* committed 20 writes, in
term 1, to the same indexes:

```
0002811 t=000622 n1     commit           entry_term=1 how=majority index=24 previous=23 term=1
0002814 t=000622 n1     apply            digest=5c0d1e9f2b3a entry=command index=24 result="ok 'v420.3'" term=1
...
0003905 t=000871 n4     commit           entry_term=2 how=majority index=24 previous=23 term=2
0003906 t=000871 -      violation        detail='index 24 committed as 24/1:set b3=v420.3 (term 1) by n1 at tick 622 but n4 committed 24/2:noop (term 2)' violation=state_machine_safety
```

Clients on both sides were told their writes were durable. When the
partition healed one side's writes were going to be truncated, and both
sides had applied theirs.

## What we found

The leader's commit rule counted acknowledgements like this:

```python
acks = 1 + sum(1 for m in self.match_index.values() if m >= index)
if acks > len(self.match_index) // 2: ...
```

`self.match_index` had one entry per *peer that had ever responded in this
term*. After the partition, `n3`, `n4` and `n5` stopped responding; the
leader's bookkeeping had been reset at the start of the term, so
`match_index` held only `n2`. One peer plus itself was two of two: a
"majority".

The rule the code was trying to express is "a majority of the cluster".
The rule it expressed was "a majority of the nodes I have heard from",
which is always satisfiable by a leader that has heard from nobody.

## The rule

A majority is `size // 2 + 1` of the voters in the node's current
`Configuration`, counted over acknowledgements from members of that
configuration, with the leader counting itself (`SPEC.md` 4.1–4.2). The
number of nodes that answered is irrelevant; acknowledgements from
non-members are ignored. Votes in an election are counted the same way
(`SPEC.md` 2.5). `Configuration.has_majority(acks)` is the one place that
does the arithmetic and nothing else may do it.

## Why this gets its own incident

The fix is one line. The reason it is recorded is that the same mistake
has three more disguises that the fixed membership of the seed hides:

* counting votes from a server that has been removed from the
  configuration (`SPEC.md` 7.6);
* counting a single majority during a joint configuration when two are
  required (`SPEC.md` 7.2);
* a leader that is not in `C_new` counting itself towards the `new`
  majority (`SPEC.md` 7.5).
* counting the machine an answer arrived through as well as the machine the
  answer names. A grant travels — a link that forwards, a proxy, an answer
  that came back by the way the request came — and the peer the transport
  reports is not a voter. The set handed to `has_majority` is a set of
  *voters*, taken from the payloads; if a name gets into it because a socket
  said so, the arithmetic is over "the machines I heard from" again.

Every one of these is "majority of the wrong set". `Configuration` exists,
and `has_majority` filters by membership, so that when membership change
arrives the arithmetic has one home. `ADR-0007` records the design;
`tests/test_replication.py::test_leader_counts_a_majority_of_the_configuration_not_of_responders`
pins the seed's behaviour, including that an acknowledgement from a
stranger (`n9`) is ignored.

## How it was diagnosed

Two `commit` events for the same index with different `entry_term` from
two different leaders, during a partition, is unambiguous. `grep "commit
.*n1"` after the partition tick showed `n1` committing with `how=majority`
while `grep "deliver .*dst=n1"` showed deliveries from `n2` only. A leader
committing with acknowledgements from one peer in a five-node cluster is
the whole diagnosis.

## What changed

* `Node._advance_commit_index` builds the set of acknowledging node ids
  and asks `self.config.has_majority(acks)`.
* `Node._handle_vote_response` and the pre-vote tally do the same.
* `Node._become_leader` initialises `match_index` for every peer in the
  configuration, so a reader of the state sees the full set.
* `schedules/partition-minority` cuts three different pairs off in turn so
  that the leader is in the minority at least once per seed.

## What to check if you see this again

`state_machine_safety` with two `commit` events at the same index from
leaders of different terms, overlapping a `partition` … `heal` interval,
is a majority-counting bug. Read `Node._advance_commit_index` and confirm
the majority is `config.has_majority(...)` and not a ratio over whatever
dictionary happens to be at hand. If the commits are from the *same*
leader and term, it is INC-0005 (a follower lost entries it acknowledged).
If the second commit comes after a `restart` on the first leader, see
INC-0003.

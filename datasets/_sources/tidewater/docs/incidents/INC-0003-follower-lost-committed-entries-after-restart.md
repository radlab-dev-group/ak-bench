# INC-0003: A follower lost committed entries after a restart

Severity: safety (`leader_completeness`). Schedule: a three-node
hand-written scenario, now `tests/test_cluster.py::test_losing_durable_state_on_crash_violates_leader_completeness`.
Status: closed as a test of the seam; rules in `SPEC.md` 3.6, 5.2–5.5;
decision ADR-0012.

## Symptom

```
0000731 t=000123 -      violation        detail='leader n2 (term 2) holds term 2 at index 2, which was committed with term 1 by n3 at tick 66' violation=leader_completeness
```

Three nodes. `n3` led term 1 and committed index 2 (`set durable=yes`)
with `n2`'s acknowledgement while `n1` was cut off. `n2` crashed at tick 70
and restarted at tick 75. `n3` was then cut off from both. `n1` and `n2`
elected `n2` in term 2; `n2`'s no-op went in at index 2, over the top of
the committed entry.

## What we found

`n2` had acknowledged index 2 with `success=True, match_index=2`. The
leader counted that acknowledgement — correctly, under the rules — and
committed. `n2`'s log after restart was empty: `restart ... last_index=0
term=0 vote=None`. Nothing `n2` had written survived the crash.

This run used `sync_policy = "never"`, the storage policy under which
`sync()` is a no-op. In other words, the follower was modelling a server
whose disk does not honour fsync. The protocol's persistence contract was
followed to the letter by the node code — `save_log` then `sync` then
reply — and it did not matter, because the sync did nothing.

That is the point of the incident: it is a *demonstration* that the
contract is load-bearing, kept as a test so that the demonstration stays
true. The same scenario under `sync_policy = "always"` elects `n2` (the
only node whose log is complete, by the up-to-date rule in `SPEC.md` 2.6)
and commits nothing wrong; under `never` the up-to-date rule has nothing
to work with because `n2`'s log is as empty as `n1`'s.

## The rule

`SPEC.md` 3.6 and 5.2: a follower that appended or truncated anything
persists and syncs the log before placing its acknowledgement in the
outbox. The leader is entitled to count an acknowledgement as a durable
replica. A storage whose `sync()` does not make writes durable is outside
the contract and the invariant monitor will, eventually, say so.

## How it was diagnosed

The violation detail names the committed entry, the node that committed
it, the tick, and the leader that now holds something else at that index.
From there: `grep "n2 .*restart"` showed `last_index=0`; the `crash` event
before it showed `lost_writes=1`; the schedule's `sync_policy` explained
why. Under `always` the same `crash` event would show `lost_writes=0` and
the `restart` would show `last_index=2`.

## What changed

* Nothing in the node. The scenario became a pair of tests
  (`always` passes, `never` violates) so that any future change to the
  sync points is caught by the pair diverging in the wrong direction: if
  someone removes the follower-side sync, the `always` test still passes
  (because `always` syncs on every write) but the `explicit` policy would
  not, so the test pair was later extended to run under `explicit` as well
  in the hidden acceptance suite.
* `Storage.sync_policy = "never"` was kept rather than removed, because a
  policy that can show the failure is worth more than a policy set that
  cannot.

## What to check if you see this again

`leader_completeness` whose detail says the new leader "holds term X at
index I, which was committed with term Y" means the new leader's no-op (or
first entry) overwrote a committed index. Either a node that acknowledged
the commit lost its log (look for `restart` with a smaller `last_index`
than the preceding `crash`), or the acknowledgement was counted when it
should not have been (INC-0008), or the commit was made under the wrong
term rule (INC-0004). The `lost_writes` field on the `crash` event
separates the first from the other two.

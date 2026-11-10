# INC-0004: A committed write vanished after two leader changes

Severity: safety (`state_machine_safety`, `leader_completeness`). Schedule:
a hand-built five-node scenario; the corpus's `crash-leader-chain` is its
descendant. Status: closed; rule in `SPEC.md` 4.1, 2.8; decision ADR-0004.

## Symptom

A client was told that `set k=v1` (log index 2) was committed. Four
hundred ticks and two leader changes later, every node's state machine
held `k=v2`, from a *different* entry at index 2. The monitor reported:

```
0006208 t=002031 -      violation        detail='index 2 committed as 2/2:set k=v1 (term 2) by n1 at tick 1620 but n5 committed 2/3:set k=v2 (term 3)' violation=state_machine_safety
```

The run had passed every invariant for 2030 ticks. The entry at index 2
had been committed, acknowledged, applied on three nodes, and then
replaced.

## What we found

This is the scenario in Figure 8 of the Raft paper, which we had read and
had not believed applied to us. In order:

1. `n1` leads term 2, appends index 2 (`set k=v1`), replicates it to `n2`,
   and crashes before the acknowledgement arrives.
2. `n5` wins term 3 (votes from `n3`, `n4`, whose logs end at index 1),
   appends its own index 2 (`set k=v2`, term 3), and crashes before
   replicating it to anyone.
3. `n1` restarts and wins term 4. It resumes replicating its index 2
   (term 2) and gets it onto `n3`. Three of five now hold `2/2`. The
   prototype's commit rule — "a majority holds it" — fires. `n1` commits
   index 2 and the client is told the write is durable.
4. `n1` crashes. `n5` restarts and asks for votes in term 5 with
   `last_log_index=2, last_log_term=3`. `n2`, `n3`, `n4` each compare: their
   last term is 2, `n5`'s is 3, so `n5` is more up to date. `n5` wins,
   replicates `2/3` to everybody, and `2/2` is gone.

Nothing in step 4 is wrong. The up-to-date rule is doing exactly what it
should. The mistake is in step 3: holding an old-term entry on a majority
does not make it safe, because the up-to-date rule compares *terms* first,
and a node with a higher-term entry at the same index can still win.

## The rule

A leader commits only an index whose entry carries the leader's *current*
term, by counting a majority of the configuration (`SPEC.md` 4.1). Earlier
entries below it become committed as a consequence. To make sure there is
always such an entry, a new leader appends a no-op in its own term as its
first act (`SPEC.md` 2.8). In the scenario above, step 3 would have `n1`
append a no-op at index 3 (term 4); index 2 commits only once the no-op is
on a majority; and `n5`, whose log ends at `2/3`, can no longer out-vote
nodes holding `3/4`.

## How it was diagnosed

The violation detail gave both entries, both terms, both nodes and both
ticks. `grep "commit .*index=2"` found the first commit on `n1` at tick
1620 with `entry_term=2 term=4` — a commit of a term-2 entry by a term-4
leader, which is the thing the rule forbids. Once you know to look for
`entry_term != term` in `commit` events, the trace tells you in one line.
The `commit` event now carries both fields for exactly this reason.

## What changed

* `Node._advance_commit_index` skips indexes whose term is not the current
  term.
* `Node._become_leader` appends a no-op.
* The `commit` event carries `entry_term` and `term`.
* `tests/test_replication.py::test_leader_commits_only_entries_of_its_own_term`.

## What to check if you see this again

A `commit` event with `entry_term < term` on a leader is the bug, full
stop. If every leader `commit` has `entry_term == term` and you still see
this violation, look for the no-op: a leader that commits nothing for
hundreds of ticks after `leader ... noop_index=K` is one whose no-op is not
reaching a majority (INC-0008) or whose followers are rejecting it
(INC-0005). If the violation is `leader_completeness` rather than
`state_machine_safety`, the run stopped at step 4 before the overwrite was
applied; the diagnosis is the same.

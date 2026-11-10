# ADR-0004: A leader commits only entries of its own term; a no-op on election

Status: accepted. Supersedes: the prototype's "commit when a majority has
it" rule. Referenced by: `SPEC.md` 4.1, 2.8, `Node._advance_commit_index`,
`Node._become_leader`.

## Context

The natural commit rule — "an entry is committed when a majority of
servers hold it" — is wrong, and wrong in a way that only shows after two
leader changes. `docs/incidents/INC-0004` is our own reproduction of the
scenario in Figure 8 of the Raft paper:

1. Leader `n1` (term 2) replicates index 2 to `n2` and crashes.
2. `n5` wins term 3 with votes from `n3`, `n4` (their logs end at index 1),
   appends its own index 2 in term 3, and crashes before replicating it.
3. `n1` restarts, wins term 4, and resumes replicating its term-2 index 2.
   Once `n3` has it, three of five hold the term-2 entry. Under the natural
   rule `n1` commits index 2 and the client is told the write is durable.
4. `n1` crashes. `n5` restarts and wins term 5: its last term (3) is higher
   than everybody else's last term at index 2 (2), so `n2`, `n3`, `n4` vote
   for it. `n5` replicates *its* index 2 in term 3 everywhere, overwriting
   the committed entry.

The invariant monitor reports this as `state_machine_safety` (index 2
committed as one entry and later as another) or, if the run stops earlier,
as `leader_completeness` (the term-5 leader lacks an entry committed in
term 4).

The flaw is that holding an old-term entry on a majority says nothing about
which *leader* a future majority will elect, because election
up-to-dateness compares terms before indexes.

## Decision

1. A leader may set `commit_index` to `N` only if `log[N].term ==
   current_term` and a majority of the current configuration has
   `match_index >= N` (`SPEC.md` 4.1). Earlier-term entries below `N` become
   committed as a consequence, never on their own.
2. To make this rule useful, a new leader appends a **no-op entry** in its
   own term immediately on election (`SPEC.md` 2.8). Once the no-op is on a
   majority, everything below it is committed, so a leader with no client
   traffic still commits the previous leaders' entries.

## Alternatives considered

* **Commit old-term entries by counting replicas, but only when the leader
  has also replicated a current-term entry to the same majority.** This is
  the same rule stated less clearly.
* **Rewrite old-term entries with the current term when re-replicating
  them** (what some Paxos variants do). Rejected: it breaks the log
  matching property (two logs with the same term at an index would no
  longer be guaranteed to agree below it) and every proof that depends on
  it.
* **No no-op; wait for client traffic.** Rejected: a leader elected into a
  quiet cluster would never commit its predecessors' last entries, and
  read-only requests that wait for `commit_index >= last_index` would hang.

## Consequences

* The first entry a new leader commits is always its no-op. A trace shows
  `leader ... noop_index=K` followed, one round trip later, by `commit
  index=K` — and only then do any pending old-term indexes appear as
  committed.
* The no-op occupies an index. Clients that compute indexes from their own
  proposal count are wrong; nothing in the simulator does that.
* `tests/test_replication.py::test_leader_commits_only_entries_of_its_own_term`
  pins the rule: a majority on an old-term entry does not commit it; a
  majority on the next current-term entry commits both.
* The `how` field of a `commit` event is `majority` on the leader and
  `leader` on followers; the digest covers both, so a change to *when* a
  leader commits is visible in every reference digest.

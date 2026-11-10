# ADR-0005: A follower truncates its log only at a term conflict

Status: accepted. Supersedes: the prototype's "truncate after
`prev_log_index` and copy" rule. Referenced by: `SPEC.md` 3.3,
`RaftLog.append_from_leader`.

## Context

The simplest way to implement `AppendEntries` on a follower is: check the
prefix; if it matches, delete everything after `prev_log_index` and append
the incoming entries. It is short, it is obviously "consistent with the
leader", and it is wrong under reordering and duplication.

`docs/incidents/INC-0005` is the case. A leader sends two appends in the
same tick: A with entries 5–6 and B with entries 7–8 (because an
acknowledgement arrived between them). The network delivers B first. The
follower rejects B (it has no index 6), then accepts A and holds 5–6. A
duplicate of A — the network duplicated it — arrives later, after the
follower has also accepted a retransmitted B and holds 5–8. Under
"truncate after prev and copy", the duplicate of A (prev 4, entries 5–6)
truncates 7–8 and re-appends 5–6. The follower has just thrown away two
entries it had acknowledged — and if the leader counted that
acknowledgement towards a commit, it has thrown away *committed* entries.

The invariant monitor catches this as `log_matching` or
`leader_completeness` depending on which node is elected next. In the
incident it was neither, for 400 ticks, because the leader re-sent the
entries and nothing looked wrong until the leader crashed.

## Decision

A follower whose prefix check passes walks the incoming entries in order:

* an index it does not have is appended;
* an index it has with the **same term** is left alone;
* the first index it has with a **different term** causes truncation from
  that index; the incoming entry and all following ones are appended.

Nothing after the last incoming entry is touched unless a conflict was
found. A stale or duplicated append whose entries are all already present
changes nothing and is acknowledged with `match_index = prev_log_index +
len(entries)`, exactly as if it had been applied.

## Why this is safe

If the follower holds an entry at index `i` with the same term as the
leader's entry at `i`, the log matching property says the two entries are
identical and so is everything below them. Keeping the follower's copy is
therefore keeping the leader's copy. Entries above the incoming batch that
the follower already holds were accepted from *a* leader of some term; if
they conflict with the current leader's log, a later append covering them
will carry a different term at their index and truncate them then. If they
do not conflict, they are the leader's own entries and deleting them would
be pointless destruction.

## Alternatives considered

* **Truncate after prev and copy, but only if `len(entries) > 0`.**
  Heartbeats then stop truncating, but a delayed non-empty append still
  does. Rejected.
* **Reject any append whose entries are all already present.** Safe but
  wrong in a different way: the leader interprets the rejection as a
  mismatch and backs up `next_index`. Rejected.
* **Make the network deliver in order and never duplicate.** The seed's
  network can be configured that way, but the rule has to hold under the
  network the schedule corpus uses, which duplicates and reorders on
  purpose.

## Consequences

* `tests/test_log.py::test_append_from_leader_keeps_matching_entries_and_truncates_only_on_conflict`
  and
  `tests/test_replication.py::test_follower_keeps_entries_on_stale_duplicate_and_truncates_only_on_conflict`
  pin the rule.
* The `truncate` trace event records `removed`; in a healthy run it appears
  only after a leader change, on nodes that followed the deposed leader.
  A `truncate` on a follower under a stable leader is a bug.
* `schedules/lossy-network` (15% drops, 10% duplicates, delay 1–6) is the
  corpus's standing reproduction of the conditions in INC-0005.

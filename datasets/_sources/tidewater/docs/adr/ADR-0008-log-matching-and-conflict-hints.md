# ADR-0008: Log matching by (prev_log_index, prev_log_term), with conflict hints

Status: accepted. Supersedes: the prototype's "send the whole log" and its
"back up one index per rejection" variants. Referenced by: `SPEC.md`
3.1–3.5, `RaftLog.matches`, `RaftLog.conflict_hint`,
`Node._handle_append_response`.

## Context

Replication has to establish that a follower's log agrees with the
leader's up to some point before new entries are appended after that
point. There are three ways to do it and we have tried all three.

**Send the whole log every time.** The prototype did this. It is trivially
correct and the trace of a 2000-tick run was 40 MB. Rejected before the
first incident.

**Send `prev_log_index` and `prev_log_term`; on mismatch, back up by one.**
Correct, and the standard presentation. Under `schedules/crash-leader-chain`
a restarted follower that missed 60 entries took 60 round trips — about
250 ticks with the corpus network — to catch up, during which the leader
could not commit anything that needed that follower's acknowledgement.

**Send `prev_log_index` and `prev_log_term`; on mismatch, the follower says
where its disagreement starts.** This is the decision.

## Decision

1. Every `AppendEntries` carries the index and term of the entry
   immediately preceding the batch. A follower accepts only if it holds an
   entry at that index with that term; index 0, term 0 is the empty prefix
   and always matches (`SPEC.md` 3.2).
2. On a mismatch the follower replies with a **conflict hint**: if it has
   an entry at `prev_log_index`, `conflict_term` is that entry's term and
   `conflict_index` is the first index of that term in its log; if it has no
   entry there, `conflict_index` is `last_index + 1` and `conflict_term`
   is 0 (`SPEC.md` 3.4).
3. The leader uses the hint to set `next_index`: if it has entries of
   `conflict_term`, to the index after its last one (the follower's entries
   of that term up to there are correct); otherwise to `conflict_index`
   (none of the follower's entries of that term are). It always backs up by
   at least one and never below its first retained index. It resends at
   once.
4. The matching check and the conflict hint live in `RaftLog`, not in the
   node, so that they are tested on logs directly and the node code reads
   as the protocol.

## Why the term of the previous entry and not a hash of the prefix

A hash would detect disagreement too, but it cannot say *where*, so the
leader would still back up one index at a time. The term is enough because
of the log matching property: equal term at an index implies equal prefix.
The hint is one round trip per *term* of disagreement rather than per
*entry*, and the number of terms is small.

## Alternatives considered

* **Binary search over indexes.** Faster in the worst case, more round
  trips in the common case (one term behind), and more state on the leader.
* **Follower sends its last `k` (index, term) pairs with every rejection.**
  Helps only if the disagreement is within `k`.

## Consequences

* The compacted boundary participates in matching like an entry
  (ADR-0006), so the rule survives compaction.
* `tests/test_log.py::test_append_from_leader_rejects_mismatched_prefix_without_change`
  pins the hint values;
  `tests/test_replication.py::test_leader_backs_up_next_index_from_the_conflict_hint`
  pins the leader's use of them.
* A follower that has lost its log entirely (a broken disk; `sync_policy
  = never`) replies `conflict_index = 1, conflict_term = 0`, and the
  leader resends from index 1 in `max_entries_per_append`-sized batches.
  `schedules/crash-restart-follower` with a 16-entry batch catches up a
  60-entry gap in four round trips.
* The `reject_append` trace event carries both hint fields, so a trace
  shows the back-up as a sequence of decreasing `prev` values.

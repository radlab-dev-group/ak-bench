# INC-0005: A follower's log shrank on a delayed, duplicated append

Severity: safety (`log_matching`, then `leader_completeness`). Schedule:
an ancestor of `lossy-network`. Status: closed; rule in `SPEC.md` 3.3;
decision ADR-0005.

## Symptom

Under 10% duplication and delay 1–6, a follower that had acknowledged
entries up to index 48 was later found holding only 46 entries, with no
`truncate` event that made sense:

```
0003312 t=001104 n3     append           count=2 first=47 last_index=48 last_term=2 term=2
0003330 t=001106 n3     truncate         last_index=46 removed=2 term=2
0003331 t=001106 n3     append           count=2 first=45 last_index=46 last_term=2 term=2
```

A truncation *under a stable leader in the same term*, immediately
followed by an append of entries the node already had. The leader had
counted `n3`'s acknowledgement of 48 towards committing 47–48. When the
leader crashed 300 ticks later and `n3` was elected (its log looked most
up to date by term), the new leader lacked committed entries:

```
0004871 t=001419 -      violation        detail='leader n3 (term 3) lacks index 47, committed in term 2 by n1 at tick 1105' violation=leader_completeness
```

## What we found

The follower's `AppendEntries` handler was the textbook three-liner:
check the prefix; if it matches, delete everything after `prev_log_index`;
append the incoming entries. At tick 1104 the leader's append with
`prev=46, entries=47–48` arrived and was applied. At tick 1106 a
*duplicate* of an earlier append — `prev=44, entries=45–46`, duplicated by
the network at tick 1100 with an extra 5 ticks of delay — arrived. Its
prefix matched (the follower had index 44 with the right term). The
handler deleted everything after 44 and re-appended 45–46. Entries 47–48,
acknowledged two ticks earlier, were gone.

The follower was not misbehaving by its own lights: the leader had sent
exactly that message. It was treating "the leader sent prev=44 and two
entries" as "the leader's log ends at 46", which is only true if the
message is the newest one, and nothing in the message says so.

## The rule

A follower whose prefix matches walks the incoming entries and truncates
only at the first index where its own entry's term differs from the
incoming one (`SPEC.md` 3.3). Entries it already holds with the same term
are kept; entries beyond the incoming batch are not touched unless a
conflict was found. A delayed or duplicated append whose entries are all
present is a no-op that is still acknowledged.

## How it was diagnosed

The `truncate` event under a stable leader was the tell; in a correct run
`truncate` appears only on followers of a deposed leader after a term
change. `grep "deliver .*dst=n3 .*AppendEntries"` around tick 1106 showed
the delivery with `sent=1100` — six ticks in flight, longer than the
delay range of 1–3 — and `grep "dup .*of=<seq>"` showed it was a
duplicate. The sequence numbers in `send`/`dup`/`deliver` events exist to
make this traceable.

## What changed

* `RaftLog.append_from_leader` implements the walk and returns
  `(accepted, truncated, appended, match_index)`.
* `Node._handle_append_entries` uses it and traces `truncate` only when
  `truncated > 0`.
* `tests/test_log.py` and `tests/test_replication.py` pin a stale duplicate
  changing nothing and a genuine conflict truncating from the right index.
* `schedules/lossy-network` runs with `dup_rate 0.10` and later `0.20`
  precisely so the conditions of this incident are permanent in the corpus.

## What to check if you see this again

Any `truncate` event on a node whose `term` field equals the current
leader's term, with no `step_down` or `leader` event in between, is this
bug or a close relative. Confirm with the `deliver` event immediately
before it: if `sent` is well before `t` and a `dup` event names its
sequence number, the append was a duplicate. Then read
`append_from_leader` and check that it compares terms at each index rather
than cutting at `prev_log_index + 1`. If the `truncate` follows a
`step_down` instead, it is the normal post-election reconciliation and
not an incident.

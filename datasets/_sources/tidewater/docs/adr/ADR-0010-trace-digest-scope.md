# ADR-0010: The trace digest covers only committed-visible events

Status: accepted. Supersedes: the prototype's whole-trace hash.
Referenced by: `SPEC.md` 8.4, `tidewater.trace.DIGEST_KINDS`,
`tools/reference_traces.py`.

## Context

A deterministic simulator wants a short name for a run so that "did my
change alter behaviour?" is a comparison of two strings. The obvious name
is a hash of the whole trace. We shipped that first, and
`docs/incidents/INC-0006` is what happened: a refactor that changed the
order in which a node drained its outbox — same messages, same ticks, two
lines swapped in the trace — turned every reference digest red. The author
regenerated all twelve, as the tooling at the time invited them to, and in
doing so also accepted a second, unintended change in the same commit that
moved a commit by thirty ticks on `long-haul`. Nobody noticed for two
weeks.

The whole-trace hash was too sensitive to be a useful alarm. An alarm that
fires on every harmless change gets silenced, and then it does not fire on
the harmful one.

## Decision

1. `Trace.digest()` hashes only events whose kind is in
   `DIGEST_KINDS = ("commit", "apply", "violation")` — the
   **committed-visible** events: what was committed, by whom, at which
   tick, with which entry term; what was applied, in which order, with the
   resulting state digest; and whether safety was ever violated.
2. The hashed material is the canonical JSON of `(tick, node, kind,
   fields)`. The sequence number is excluded, because message-level events
   between two commits shift it without meaning anything.
3. Message-level events (`send`, `deliver`, `drop`, `dup`) and
   election-level events (`timeout`, `prevote*`, `election_start`, `vote`,
   `leader`, `step_down`) are **not** in the digest. They remain in the
   trace and `tools/replay_trace.py --all` compares them when asked.
4. `tools/reference_traces.py --check` distinguishes a changed *input* (the
   schedule's own digest moved) from a changed *output* (the trace digest
   moved) and says which.

## Why tick numbers stay in

A tempting further step is to hash only the *sequence* of committed entries
and drop ticks, so that a timing change does not show. We kept ticks
because the question the digest answers is "did behaviour change", and a
commit that happens thirty ticks later *is* a behaviour change — it is
exactly what INC-0006 missed. A change that is meant to alter timing
(say, a smaller heartbeat interval) is a situation-B change in the runbook
and regenerates the digests with an explanation; that is the right amount
of friction.

## Why `apply` and not only `commit`

`commit` on a follower says the follower learned the leader's commit
index. `apply` says what the follower's state machine did with the entries,
and carries the state digest after each one. A bug that commits the right
indexes but applies them in the wrong order, or applies an entry twice
after a restart, shows in `apply` and not in `commit`. Both are cheap to
include.

## Alternatives considered

* **Hash the final state only** (the KV maps at the end of the run).
  Rejected: a run that reaches the right final state by way of an
  intermediate state-machine-safety violation that was later overwritten
  would pass.
* **Hash leader elections too** (`leader` events). Considered; rejected
  because an election that happens at a different tick but commits the
  same things at the same ticks is a timing detail of the kind the digest
  is meant to ignore. Election safety is checked by the invariant monitor,
  not by the digest.
* **Two digests, strict and loose.** Rejected as doubling the artefacts
  for a distinction `replay_trace.py --all` already provides on demand.

## Consequences

* `tests/test_messages_trace.py::test_trace_is_append_only_and_digest_covers_only_committed_visible_kinds`
  pins the set and the exclusion of message events.
* Adding a committed-visible kind (the declared `snapshot` and
  `snapshot_installed` events) is a digest-breaking change by definition
  and follows the runbook.
* Renaming or re-typing a field of a `commit` or `apply` event is also
  digest-breaking. The fields are part of the contract (`SPEC.md` 8.4).
* A `.digest` file records `events` and `digest_events` separately so a
  reader can see at a glance whether a mismatch came with a change in the
  number of committed-visible events or only in their content.

# Contributing to WALQueue

This file says which document to believe, what counts as evidence, and what
is not allowed in a change. Read it before changing anything under `src/`.

## The hierarchy of truth

When two documents disagree, the one higher in this list is right and the
lower one has a bug that should be fixed in the same change:

1. **`docs/adr/`** — decision records. Each one records a decision, the
   symptom that made the decision necessary, and the rule that now holds.
   An ADR is never edited to say something different; it is superseded by a
   new ADR that names it. When code and a decision record disagree, the code
   is wrong.
2. **`README.md`** — the contract of the queue: the semantics, the storage
   and recovery contract, and the fault-injection phases. It is written for
   a first read and is deliberately approximate where a decision record has
   taken a position after it was written; do not quote the README as the
   rule when the two disagree.
3. **Module docstrings and comments in `src/`** — explanations of how a rule
   is implemented. They may lag the record.

**Incident reports (`docs/incidents/`) are evidence, not rules.** They
describe a symptom, what was found, and which rule turned out to be the one
that mattered. They are written by symptom on purpose: when you are looking
at a store that refused to open after a compaction you do not yet know which
step of the compaction is at fault, so the index is "what did it look
like", not "where was the bug". When an incident contradicts a decision
record, the incident is a report that the record was violated, not a
redefinition of it.

## Determinism is a hard requirement

* No threads, no wall clock, no `time.sleep`, no network. Time is an explicit
  nonnegative integer passed to the API.
* Raising `InjectedCrash` from a hook simulates process death. After a hook
  raises, the Queue is dead; discard it and reopen the directory.
* A scenario is reproducible by calling the API in a fixed order. If it
  needs a wait, the wait is a number, not a sleep.

## The compaction contract

The four phases of a compaction are a contract, and so are their crash
points (`compact.rotated`, `compact.snapshot`, `compact.manifest`,
`compact.pruned`). A restart must be observationally equivalent to
uninterrupted execution at every one of them. A change to the compaction is
judged by the crash matrix — each crash point, a restart, a further
compaction, a second restart — not by a compaction that runs to completion,
because the swap of two steps that are both reached is invisible to a
compaction that finishes.

The rules the compaction lives by are written down in `docs/adr/`:

* `ADR-0001` — a segment name is issued once, and the newest segment is the
  append point.
* `ADR-0002` — CURRENT is published before the WAL is pruned.
* `ADR-0003` — only the newest segment may end in a torn frame.

## Things that are not changes

The disk format (the frame layout, the envelope, the names `wal-*.log` and
`snapshot-*.json`, and the `CURRENT` pointer) is frozen. The phase names of
the fault-injection hooks are a contract with the tests. The repository
suite under `tests/` must stay green on every change, and it is not the
proof: it reaches one subsystem at a time. The proof of a compaction change
is a crash scenario written as a test.

## Style

Standard library only. No third-party dependencies. Module docstrings state
the rule that lives in the module; comments cite ADR numbers rather than
restating code. Error messages are stable and are matched on by tests, so
changing one is a behaviour change, not a cosmetic one.

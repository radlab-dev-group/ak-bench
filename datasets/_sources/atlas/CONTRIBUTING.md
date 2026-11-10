# Contributing to Atlas

Atlas is small enough to read in an afternoon and old enough to have been
wrong in most of the ways a store can be wrong. The documents in this
repository disagree with each other now and then, because they were written
at different times for different readers. When they do, this is the order
that settles it.

## The hierarchy of truth

1. **`docs/adr/`** — architecture decision records. A decision record states
   a rule, the symptom that made the rule necessary, and the invariant the
   rule protects. When code and a decision record disagree, the code is
   wrong. When `SPEC.md` and a decision record disagree, the decision record
   is newer and wins; the specification is corrected afterwards, not before.
2. **`SPEC.md`** — the normative contract of the store: identity and time,
   placement, durability, snapshots, fencing, replication, rebalancing,
   configuration, lineage. It is complete for the behaviour it describes and
   silent about the decisions taken after it was written.
3. **`README.md`** — the map. It names the modules and the five rules that
   everything else follows from. It is deliberately short and occasionally a
   release behind; read it first and trust it last.
4. **`docs/incidents/`** — the incident archive. An incident note records
   what an operator saw, what it turned out to be, and what was changed. It
   is **evidence, not a rule**: the module an incident names is the module
   that was at fault *that time*, and about one note in ten names the wrong
   one, because the note was written before anyone knew. Use the archive to
   recognise a symptom; use a decision record to decide what to do about it.

Docstrings rank below all of the above. A docstring describes what a function
does today, which is not the same as what it should do.

## How to change behaviour

* Find the decision record that owns the invariant. If none does, write one
  before changing the code, in the same shape as the existing ones: context,
  the symptom, the decision, the consequences. Number it next in sequence.
* Change the code to match the record. A change that makes one test pass and
  another fail with the same error is not a fix, it is the other half of the
  same bug, and the record will say so.
* The repository suite must stay green, and it is not the proof: it reaches
  one subsystem at a time. The proof is the cross-module scenario — partition,
  repair, drain, rebalance, in a fixed order — written as a test.

## Things that are not changes

`src/atlas/tables.py` is generated; editing it is not a change. The vendored
v1 ring under `src/atlas/vendor/` and `src/atlas/compat.py` compute placement
differently on purpose and are not on the write path. The crash points in
`src/atlas/faults.py` are a contract: adding one is a decision record.

## Style

Standard library only. No threads, no timers, no sleeps: every scenario must
be reproducible by calling methods in a fixed order. Error types carry a
stable `code`; tests match on the type and on the message pattern the
decision record states, never on an incidental word.

# Restore the compaction rules of a durable queue

WALQueue is a single-writer durable queue. Its repository suite is green, and
yet a store that has been compacting on a cadence reports four failure modes
that appear only when the compaction path meets a crash or its own leftovers:

* the store **dies on the second compaction of a run** with a file-already-
  exists error that names a segment the first compaction of the run deleted;
* a compaction succeeds, but the **next write lands in the segment the
  compaction deleted**, so the directory afterwards holds two segments where
  one should;
* a store that was interrupted mid-compaction and then mid-write **refuses to
  open** with an incomplete-frame error naming a segment that was the append
  point, not a sealed one; and on the same directory torn in the other
  segment, a restart **quietly truncates a real frame** instead of refusing
  it;
* a compaction interrupted before it publishes **loses acknowledged work**:
  the store comes back with a lower sequence and the tasks written since the
  previous compaction are not there, with no error anywhere.

Each of the four is a small change in one module. Two of them are the point:
the rotation step and the append target are two halves of one rule, and the
change that makes the first symptom go away brings the second one back on the
next compaction with the same error, and the change that makes the second go
away brings the first back. Oscillating between the two is what the operators
did for a week. The resolution is a rule, not a compromise, and the rule for
each pair is written down in exactly one place.

`CONTRIBUTING.md` states where the truth lives: the decision records under
`docs/adr/` outrank `README.md`, which outranks the module comments, and the
notes under `docs/incidents/` are evidence of what happened, not rules about
what should. One of the recent incident notes about these symptoms names a
module that is not at fault, as a real incident log would, and another one
keeps a first-draft diagnosis that was wrong. The decision records are
written about symptoms and invariants, not about modules, so they are not
found by searching for the module name.

Hidden tests drive the store through three compactions with work between
them, a crash at every publication point, and interrupted writes, using the
queue's deterministic crash points where a crash is part of the scenario.
Public tests state the complaints as the operators phrased them.

Keep the public API, the storage format, the fault-injection phases, and the
repository suite intact. Do not edit the decision records or the incident
corpus to match the code. A compaction that runs to completion is not the
proof of a compaction fix; the crash points are.

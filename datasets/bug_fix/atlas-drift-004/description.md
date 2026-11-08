# The window opens after the number, not at it

Atlas is a sharded, replicated, fenced key-value store. Its repository suite
is green, and yet a production cluster reports one failure mode that appears
only when a shard is opened after it has been snapshotted and written to:

* a counter that is incremented around a **snapshot** advances by two
  instead of one after a restart, and reads serve work the log says was
  already published;

The defect is one window in the module that owns the recovery path. The
documented invariant is that the replay window is **exclusive** of the
image it starts from: the snapshot is a floor, not a ceiling, and the log
replays *after* the snapshot's number, not *at* it. The change that broke it
opened the window at the image's own number, which is why a review that
counted skipped records saw *more* work skipped and found nothing wrong,
and why the repository suite, which never opens a shard between a snapshot
and a write to the same key, stays green.

The symptom is arithmetic. A counter incremented once around a snapshot
reads as if it had been incremented twice: the record the snapshot already
contains is applied a second time on open. Every value on the store that is
derived from a previous value of the same key inherits the doubling; a
plain overwrite does not, which is why the defect hides in exactly the
records nobody inspects.

`SPEC.md` is the normative contract and `README.md` is the map. The rule
that matters here is the one `README.md` lists under *the five rules
everything else follows from*: the **exclusive** boundary.

`docs/incidents/` holds two hundred notes about the cluster's past. One of
them is titled *the window opens after the number, not at it*, and another
records the inclusive change that was tried, measured, and reverted — the
reverted commit is still in the history, and the note about it is written
about the symptom, a counter that doubled, rather than about the module, so
it is not found by searching for the module name. A third note in the corpus
describes a different window — the one the snapshot itself uses when it
decides what to include — and reads, at a glance, like it is about this
one; it is about publication, not replay, and it is the note that makes a
plausible-looking fix plausible.

Use `tools/parity.py` to drive the store against a deliberately naive model.
It is the fastest way to see a divergence and the slowest way to understand
one, because the model knows three rules and the store has more than three.

Keep the public API, the wire format, the crash contract, and the repository
suite intact. The vendored v1 ring in `atlas/vendor` and the generated tables
in `atlas/tables.py` are not the write path and are not where the defect
lives.

# ADR-0003: Only the newest segment may end in a torn frame

Status: accepted. The README says that only an incomplete final frame in the
newest WAL segment is a recoverable torn tail, and that incomplete sealed
segments are corruption. This record says why the two sentences are one rule
and what breaks when the allowance follows the list instead of the name.

## Context

A compaction leaves two segments on disk until the next prune finishes: the
sealed segment that still explains the old CURRENT, and the empty one that
the rotation created. A write interrupted in that window leaves an incomplete
frame in the newest segment. The torn-tail allowance was moved from the
segment the journal appends to onto the first segment the journal lists, and
two symptoms appeared at once, in the same store: a restart that was supposed
to truncate the torn tail raised *incomplete frame in sealed segment*, and —
on the same directory, torn in the other segment — a restart that was
supposed to refuse a damaged sealed segment quietly truncated it instead.

## Symptom

Either of:

* a queue that was interrupted mid-append while two segments coexist refuses
  to open with *incomplete frame in sealed segment*, naming a segment that
  was the append point, not a sealed one;
* a sealed segment whose final frame is incomplete is truncated on the next
  restart and read back as if it had never been written, instead of raising.

## Decision

The torn-tail allowance follows the name, not the list position.

* The only segment that may end in an incomplete frame is the newest one —
  the segment with the greatest number, which is the segment the journal
  appends to. Its torn tail is truncated before anything is read from it.
* Every other segment must end on a complete frame. An incomplete frame in
  one of them is corruption, full stop, whatever the list does with it.
* The two symptoms are one rule read from both ends: an allowance that is too
  narrow turns a recoverable tail into a refused store, and an allowance that
  is too wide turns a damaged sealed segment into silent loss. The rule is
  that the allowance lands on exactly one segment, and that segment is the
  newest by name.

## Consequences

* A torn tail is recoverable exactly once, at the first restart after the
  interrupted write; the truncation is persisted, so a second restart sees a
  clean tail.
* The allowance is computed from the segment names as the journal reads them,
  because the list the journal keeps in memory may outlive the files it
  names.
* The same asymmetry protects the torn-tail repair itself: a truncation
  written into a sealed segment is not a repair, it is a loss, and the store
  must refuse it the way it refuses a checksum error.

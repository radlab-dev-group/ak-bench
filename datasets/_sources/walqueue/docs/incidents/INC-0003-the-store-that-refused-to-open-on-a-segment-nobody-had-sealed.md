---
id: INC-0003
severity: high
module: journal
tags: compaction, torn-tail, crash, ops
---

# INC-0003: the store that refused to open on a segment nobody had sealed

## What we saw

A store refused to open after a restart with *incomplete frame in sealed
segment*, naming `wal-0000000000000004.log`. The operator's read of the
names was that segment 4 was a sealed segment — it was not the newest one,
there was a 5 — so the error looked exactly like the corruption case the
README describes, and the first action was to take the store offline and
investigate the disk. The disk was clean. The same store, torn in the other
segment and restarted, opened fine and reported a sequence one transaction
lower than it should have had, which nobody connected to the first symptom
at the time.

## What it turned out to be

The store had been mid-compaction, so two segments coexisted: the sealed one
and the empty one. The torn tail was in the newest segment, and the torn-tail
allowance was following the journal's list instead of the segment names, so
the newest segment was being read as a sealed one. The companion symptom —
the store that opened fine and was one transaction short — was the same
allowance landing on the other segment and truncating a real frame instead
of refusing it. The "what we saw" in the first draft of this note called the
allowance a checksum bug; that was wrong, and it is kept here because it is
the diagnosis the operator would have reached from the names alone.

## What we changed

The allowance now follows the name: the newest segment by number is the one
that may end in a torn frame, and every other segment must end on a complete
one. A torn tail in the newest segment is truncated exactly once; an
incomplete frame anywhere else is corruption. The decision record is written
about the symptom — a recoverable tail that was refused, and a damaged
segment that was not — and not about the step this note names.

## Read next

INC-0001 and INC-0002 for the naming and publication halves of the same
compaction, and the decision record that says the torn-tail allowance
follows the name, not the list.

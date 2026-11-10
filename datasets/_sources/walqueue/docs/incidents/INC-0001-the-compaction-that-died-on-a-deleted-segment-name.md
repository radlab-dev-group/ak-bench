---
id: INC-0001
severity: high
module: journal
tags: compaction, crash, ops
---

# INC-0001: the compaction that died on the name of the segment it had just deleted

## What we saw

A batch store had been compacting on a fixed cadence for weeks without
incident. After a restart that had been forced by a kernel update, the first
compaction finished and the second one died with *File exists*, naming
`wal-0000000000000002.log` — a file the operator had watched the first
compaction of the run delete. The store then refused every further
compaction with the same error, and the queue behind it kept growing. The
repository suite was green throughout.

## What it turned out to be

The restart had left the journal listing a segment that no longer existed on
disk, and the rotation step computed the next name from the list instead of
from the directory. The first compaction after the restart issued a name the
directory still held. We changed the rotation step in staging and the error
went away for one compaction and came back on the next, which is how this
note and INC-0002 were open at the same time for a week.

## What we changed

Operators now treat a *File exists* from a compaction as a naming problem,
not a disk problem, and the decision record that settles both notes is
written about the symptom — a name that is issued twice — and not about the
step this note names.

## Read next

INC-0002 for the write-side half of the same week, and the decision record
that covers both halves, which says a name is issued once and the newest
segment is the one that is written to.

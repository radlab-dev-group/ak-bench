# ADR-0001: A segment name is issued once and the newest segment is the append point

Status: accepted. The README says a compaction rotates the WAL and deletes
sealed segments; it does not say how a segment gets its name or which segment
the queue writes into once more than one exists.

## Context

A compaction is the only place where the set of WAL segments changes. It
happens while the queue is busy: the trace that kept coming back to the
operators was a store that had been compacted, restarted, compacted again —
and on the second compaction the process died with *File exists* naming a
segment that the operators had watched the compaction delete themselves. The
proposed fixes were two one-liners, one in the rotation step and one in the
step that picks the append target, and each one on its own made the *File
exists* error disappear for a compaction and bring it back on the next one.

## Symptom

Either of:

* a compaction dies with `[Errno 17] File exists: '.../wal-N.log'`, naming a
  segment whose file is already on the directory;
* a compaction succeeds, and the next write after it leaves the directory
  holding two segments — the one the compaction deleted and the empty one it
  created — so the next compaction has to choose between reissuing a name and
  keeping two segments forever.

## Decision

A segment number is a name, and a name is issued once.

* The number of the next segment is one greater than the greatest number the
  **directory** holds, not one greater than the number of segments the
  process lists and not one greater than a count of files. A number whose
  file was deleted is never reissued.
* The newest segment — the one with the greatest number — is the append
  target for every later transaction. After a compaction the journal holds
  exactly that segment, and the first write after the compaction lands in it.
  The two rules are one rule seen from two sides: a name the directory holds
  cannot be reissued, and a name the journal no longer lists cannot be the
  one that is written to.

A fix that satisfies one half and not the other is not a fix: renumbering
from the process's own list reissues a name the directory still holds, and
moving the append target to the oldest segment reissues the deleted
segment's name from the write path.

## Consequences

* After an interrupted compaction the directory may hold two segments, the
  sealed one and the empty one. The empty one is still the append target and
  still the one whose name the next compaction extends.
* The number of segments on disk is not a counter for anything. It is one
  after a successful compaction and at most two after an interrupted one, and
  nothing may be computed from it.
* A gap in the numbering (wal-1, wal-4) is normal and healthy; it records a
  name that was issued and deleted. Closing the gap by renaming is a defect
  with the same symptom as reissuing.

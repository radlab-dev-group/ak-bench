# ADR-0002: CURRENT is published before the WAL is pruned

Status: accepted. The README gives the compaction order — rotate the WAL;
write and sync the snapshot; publish and sync CURRENT; delete sealed segments
and sync the directory — and says old sealed segments may still exist after
publication. It does not say why the last two steps are in that order.

## Context

The order of the publication and the pruning was not written down, and the
code that came out of a refactor of the compaction path had the last two
steps swapped. The swap was invisible in the suite: a compaction that runs to
completion looks exactly the same either way. It showed up only in the
crash window. A store that died between the prune and the publication had
lost the WAL suffix its old CURRENT still pointed at, and the tasks that
operators had watched acknowledged were gone on the next restart — while
every repository test stayed green.

## Symptom

A compaction is interrupted before CURRENT names the new snapshot, and on
the next restart acknowledged work is missing: the recovered sequence is
lower than the one the process had, and the tasks written since the previous
compaction are not there, with no error anywhere.

## Decision

Pruning is a consequence of publication, not a step that leads to it.

* The WAL is pruned only after CURRENT names the snapshot. A crash between
  the publication and the prune may leave old segments on disk; it may never
  remove them.
* The test for that is the pointer, not the plan: the old CURRENT is still
  authoritative until the new one is synced, and every byte the old CURRENT
  can still be asked to explain has to be on disk.
* A compaction that has not published has, for the purposes of recovery, not
  happened. It must leave the store as it found it: the old snapshot, the old
  pointer, and every transaction since.

## Consequences

* After an interrupted compaction the directory may hold the sealed segment
  and the empty one together, and both of them are needed: the sealed one
  explains the old pointer, and the empty one is where the next write goes.
* Pruning before publication is detectable only by a crash in the window
  between the two steps; a compaction that runs to completion exposes
  nothing. The crash point is part of the scenario, not an accident.
* The four crash points of a compaction (the rotation, the snapshot, the
  publication, the prune) each have to leave a store that a restart reads
  back exactly as it was; a store that only survives compactions that finish
  is not durable.

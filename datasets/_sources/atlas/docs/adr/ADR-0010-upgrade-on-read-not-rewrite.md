# ADR-0010: Legacy rows are upgraded on read, never rewritten on disk

- Status: accepted
- Date: 2026-09-14
- Concerns: `atlas.evolution`, `atlas.wal`, `atlas.snapshot`; `SPEC.md` 10.4

## Context

Two older row layouts exist in the logs and snapshots of every cluster that
was rolled forward from the v1 and v2 protocols (`SPEC.md` 10.1). A current
node must read them. Two designs were on the table:

1. **rewrite**: a one-shot migration that reads every segment and snapshot,
   re-encodes each row at the current layout, and replaces the file;
2. **upgrade on read**: the reader detects a row's layout and carries it
   forward in memory; the bytes on disk are left alone.

## Decision

Upgrade on read. `atlas.evolution.decode_row` is the single point where a
payload of any declared layout becomes a current `Record`; `read_log` and
`read_snapshot` apply it to whole files. No code path in the store rewrites
a frame because of its layout. The bytes of a legacy file are identical
before and after it has been read.

## Consequences

- A rewrite is a second migration hidden inside the first. It must be
  resumable, it must cope with a crash between two segments, and it leaves a
  file that is half one layout and half another with no marker between the
  halves. Reading forward has none of those states.
- The write-ahead log's durability rule (`SPEC.md` §3) is untouched: a
  rewrite would have to re-establish "a transaction is durable when its
  COMMIT is durable" for files that were already durable, and a bug there is
  the worst class of bug this store can have.
- The cost is paid on every read of a legacy row, for as long as legacy rows
  exist. Compaction retires them naturally: a snapshot written by a current
  node is at the current layout. Nothing has to be scheduled.
- Because the bytes never change, a golden digest of a legacy frame stays
  valid forever, which is what makes the round-trip contract (`ADR-0013`)
  checkable at all.
- The hidden acceptance tests hash every fixture file before and after the
  reader has run. A reader that "helpfully" repairs a legacy segment into the
  current layout fails them.

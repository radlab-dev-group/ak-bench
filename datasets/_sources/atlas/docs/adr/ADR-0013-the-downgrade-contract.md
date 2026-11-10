# ADR-0013: The downgrade contract — exact for what came from below, lossy for what did not

- Status: accepted
- Date: 2026-10-05
- Concerns: `atlas.evolution` (`downgrade`, `PinnedReader`, `MigrationWindow`,
  `verify_round_trip`); `SPEC.md` 10.5, 10.6, 10.7

## Context

A roll from one layout to the next takes days on a large cluster. For the
length of it, nodes pinned to the older layout keep reading, and they must
keep seeing writes made by current nodes. Two mechanisms serve them:

- **dual-write**: a current node persists each write twice, once at the
  current layout and once, as a shadow `CONTROL` frame, at the pinned
  layout (`SPEC.md` 10.5);
- **downgrade**: a current node serves a pinned reader rows carried back to
  the reader's layout (`SPEC.md` 10.6).

Both need a precise definition of "the row at layout `n`", and the obvious
definitions are wrong in opposite directions.

The first temptation is to **preserve everything**: tuck the vector and the
attributes into the value so that the trip down and back up loses nothing.
A `v1` reader would then see values that no `v1` writer ever wrote, with a
shape its own code may reject, and a `v1` frame written that way would not
match any frame in the fixtures of a real `v1` cluster.

The second temptation is to **preserve nothing in particular**: emit the
current payload minus whatever the older layout lacks, and let defaults sort
out the rest. That produces payloads with extra fields (`"deleted": false`
in a `v1` row), text values that are not canonical, and tombstones that
arrive as live rows with a `null` value — all of which read back as
*something*, which is how a wrong downgrade stays unnoticed until a pinned
node disagrees with a current one about a key.

## Decision

The contract is in two halves and both are checkable by bytes:

1. **Exact for what came from below.** A frame written under layout `n`,
   upgraded to the current layout and downgraded back to `n`, is **byte for
   byte** the frame it was. `verify_round_trip` checks this and reports a
   difference as `CodecMismatch(records-v<n>, expected=…, actual=…)` and
   nothing else. This is what makes a pinned reader's view of a legacy row
   indistinguishable from the row itself.

2. **Lossy, and honestly so, for what did not.** A row born at `v3` and
   downgraded to `v1` loses its vector, its attributes, its writer and its
   timestamp, and a tombstone becomes a `null` value. The downgraded row is
   *exactly what a writer of layout `n` would have written*: the fields of
   `tables.LAYOUTS[n]` and no others, with the value as canonical text at
   `v1`. Nothing is smuggled, nothing is defaulted in.

The step definitions that satisfy both halves are the ones in `SPEC.md`
10.4 and 10.6. In particular `v1 -> v2` assigns `writer := "legacy"` and
`at := 0` because `v1` had neither, and `v2 -> v1` drops both; `v2 -> v3`
derives `deleted` from a `null` value and `v3 -> v2` folds a tombstone back
into one.

## Consequences

- The round trip is the acceptance test of the downgrade. It can only be
  checked against **fixed bytes** — the legacy fixtures and the goldens —
  which is why the codec is frozen (`ADR-0011`) and the legacy files are
  never rewritten (`ADR-0010`). Remove either and the contract becomes
  unverifiable.
- An unfinished downgrade (an extra field, a non-canonical text, a tombstone
  left as a live `null`) fails the round trip with the same message a codec
  change would. `ADR-0011` resolves the ambiguity: the codec is not the bug.
- A `PinnedReader` sees frames at or below its layout and the shadow frames
  written for it, and nothing newer. That is the gap dual-write closes and
  the reason a `MigrationWindow` may pin an older layout only: a window
  pinned to the current layout would shadow every row to itself.
- Shadow frames are `CONTROL` frames in their own committed transaction.
  Recovery ignores them, so the current reader's replay count, records and
  reopen behaviour are unchanged by a window — an invariant the acceptance
  tests assert directly.

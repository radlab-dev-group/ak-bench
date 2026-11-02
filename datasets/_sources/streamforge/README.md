# Streamforge

A Python 3.12, standard-library-only event-time engine. Run the infrastructure
suite with `PYTHONPATH=src python -m pytest tests`. The window operators,
changelog and coordinator are deliberately missing. Implement them across
`windows.py`, `reconcile.py` and `runtime.py`; helpers may be added there.

## Public processing contract

`Pipeline(partitions, windows, lateness)` fixes the partition names and named
window definitions. Times, offsets and values are exact integers; negative
event times and values are legal. There is no implicit wall clock. The five
operations are `Processor.ingest`, `advance`, `mark_idle`, `checkpoint`, and
`Processor.restore`. The CLI is an existing consumer of this API.

### Source order and identity

Each partition starts at offset -1. A new delivery must have offset exactly
one greater than its consumed offset. Repeating a previously consumed offset
with the identical Event returns no changes. Any different delivery at that
offset, or a gap, raises `OffsetConflict`. An unknown partition raises
`ValueError`. Check offset validity BEFORE identity validity.

An event_id is global across partitions. Its identity is `(key, timestamp,
value)`. A new delivery with a known id and identical identity consumes its
new source offset without adding to any aggregate or late output. A known id
with different identity raises `IdentityConflict`. Every rejection leaves ALL
state unchanged, so the corrected delivery can reuse that offset. Events do
not implicitly advance watermarks or reactivate idle partitions.

### Watermarks and lateness

The supplied Watermarks class defines progress: the global watermark is the
minimum reported progress of all non-idle partitions, once all of them have
reported. It never decreases. With no active partitions it holds its value.
Reactivation with old progress therefore never rewinds global time.

At ingestion, a unique event is late iff a global watermark exists and
`event.timestamp + lateness < watermark`. Consume the delivery, remember its
identity, and append exactly one `LateEvent(event, watermark)` to `.late`.
Equality is accepted. Accepted events update all configured windows. Ingest
may immediately produce corrections for windows that are already closed.

### Window assignment

- Fixed: `[floor(timestamp / size) * size, start + size)`.
- Sliding: every `[start, start + size)` containing the timestamp, with start
  an integer multiple of step. Size need not be divisible by step. Use floor
  division for negative timestamps. Endpoints are half-open.
- Session: each event starts `[timestamp, timestamp + gap)`. For each window
  name and key independently, merge every intersecting OR touching interval,
  transitively. The merged start is the minimum start, its end the maximum
  end, and aggregates combine once per unique accepted event. A bridging event
  may merge several already emitted sessions or reopen a closed session.

Every bucket carries count, sum, min and max. `ready(watermark)` returns all
live buckets with end <= watermark as Results in address order, where address
is `(window, key, start, end)`. With watermark None it returns no rows.

### Output, corrections and finalization

After EVERY successful ingest/advance/mark_idle, reconcile a complete ready
view against the last emitted live rows. Return all retractions first, in
address order, then all upserts, in address order. A changed row retracts its
exact previous Result and upserts its replacement. An unchanged row emits
nothing. A session merge retracts every old visible address that disappears,
even if the new merged session will not close until a future watermark.

Each Change has operation `retract` or `upsert` and a globally consecutive
sequence starting at 1. Output is returned once, never implicitly replayed by
restore. Only AFTER reconciliation, finalize buckets for which
`watermark > end + lateness`. `prune` returns their addresses. Forget their
visible rows silently: finalization must not retract a durable result. Never
keep finalized buckets in the live index. Deduplication and consumed delivery
history remain available for the entire processor lifetime.

### Checkpoints

Persist the clock, live buckets, emitted live rows, output sequence, offsets,
exact delivered Events, global identities and late side output using the
provided checksummed atomic checkpoint envelope. JSON state must be canonical
and contain no pickle, executable objects or references to external state.
The same state produces identical checkpoint bytes. A saved checkpoint is
independent of later mutations of its originating Processor.

Restore accepts an equivalent pipeline even if partition/window declarations
are reordered; incompatible pipelines, corrupt envelopes or invalid state
raise `InvalidCheckpoint`. Validate state shapes, record types, partition and
window names, offset continuity, identity consistency, aggregate bounds,
clock bounds, visible/live agreement and sequence bounds. Restore must work
in a fresh interpreter and resume with exactly the same changes and side
output as uninterrupted processing. The checkpoint is the sole durable input.

### Operator state API

`WindowIndex.document()` is a list of Result field dictionaries, ordered by
address. `WindowIndex.restore(pipeline, rows)` must round-trip this format and
reject unknown window names, duplicate addresses, invalid aggregate bounds,
misaligned fixed/sliding windows, touching live sessions or invalid session
bounds with ValueError. Live session width is at least gap, and no more than
count * gap. A single-event aggregate has equal min, max and total.

`Changelog.document()` has keys `sequence` and `visible`; visible is the same
ordered Result-dictionary format. `Changelog.restore(document)` validates
sequence type/bounds, aggregate validity and duplicate addresses. The runtime
additionally validates correspondence between these operator states, source
history and its pipeline. Operator restore returns independent mutable state.

Do not change these rules, public signatures, working infrastructure modules,
or repository tests. No additional dependencies, timing assumptions or sleeps.

# ADR-0011: The canonical form of the codec is frozen; changing it is a dead end

- Status: accepted (supersedes an attempt, reverted, see below)
- Date: 2026-09-21
- Concerns: `atlas.codec.canonical`, `atlas.evolution`, `schema/goldens/`;
  `SPEC.md` 10.6, 10.7, 10.9

## Context

Every frame on disk is `atlas.codec.encode(kind, payload)`: header, checksum
and the canonical JSON of the payload. Canonical means exactly this, and has
since the first segment was written:

- keys sorted;
- separators `,` and `:` with no whitespace;
- `ensure_ascii=False` — non-ASCII text is stored as UTF-8, not escaped;
- floats as Python's `repr` (so `3.0` stays `3.0`, `1e-07` stays `1e-07`);
- objects without a JSON form fall back to `_fallback`.

The `v1` layout stores a row's value as canonical JSON **text** inside the
payload (`SPEC.md` 10.1), so the canonical form is written into history
twice: once as the frame and once as the value of every legacy row.

## The attempt that was reverted

During the first cut of the downgrade path (`v3 -> v2 -> v1`) the golden
`records-v1` would not verify. The digests differed, the message was

```
CodecMismatch(records-v1, expected=97b212bf…, actual=…)
```

and the message carries no hint of *where* the bytes differ. The author
changed `canonical` — first the separators, then `ensure_ascii`, then the
key order — chasing the digest. Each change moved the digest and none made it
match, because the actual defect was in the downgrade (it emitted
`"deleted": false` into the `v1` payload, a field that layout does not have).
Meanwhile the change to `canonical` had silently altered the checksum of
every frame the store would write from then on, and the repository suite had
not noticed: it encodes and decodes with the same code and is therefore blind
to a consistent change of form.

The change was reverted. The downgrade was fixed by comparing the emitted
field set against `tables.LAYOUTS[1]`, which took five minutes.

## Decision

`atlas.codec.canonical` is frozen. No change to its parameters, ordering,
fallback or float handling is acceptable for any reason connected to schema
evolution, goldens or legacy layouts. The goldens under `schema/goldens/`
pin the form: `records-v1`, `records-v2`, `records-v3` and one `index-*` per
declared index are sha256 digests of frames the code must reproduce from the
fixed rows in `schema/goldens/rows.json`.

A `CodecMismatch(...)` or `GoldenMismatch(...)` therefore **always** means
the evolution code is wrong. It is never evidence that the codec needs
adjusting, and an implementer who finds the codec in their diff should treat
that as the symptom, not the fix.

## Consequences

- An unfinished downgrade and a changed canonical form produce the same
  error, byte for byte in its shape. The message cannot distinguish them;
  this decision does, by ruling one of them out.
- The repository suite stays blind to canonical drift by design — it is a
  behaviour suite, not a bytes suite. The goldens and the hidden acceptance
  tests are the bytes suite. A change that turns the public suite green and
  the goldens red is the signature of this dead end.
- The golden rows deliberately contain non-ASCII keys and values, floats,
  nested objects with unsorted keys in the source, tombstones and
  attributes, so that each of the four tempting changes breaks at least one
  golden.
- If the canonical form ever must change, that is a new frame magic
  (`ATL2`), a new schema version, and a new set of goldens — a project, not
  a fix.

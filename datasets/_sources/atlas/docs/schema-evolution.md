# Schema evolution: how a change to the schema is made real

`SPEC.md` section 10 is the contract. This is the guide: the reasoning a
maintainer needs, and the one procedure every change to `schema/tables.json`
must go through. The decisions themselves are recorded in `docs/adr/ADR-0010`
to `ADR-0013`; where this guide and an ADR disagree, the ADR is right, and
where the README disagrees with either, the README is behind.

## The shape of the problem

A row on disk has a layout. Three exist (`SPEC.md` 10.1): `v1`, the flat
layout that stored the value as JSON text; `v2`, which added a timestamp and
a writer; and `v3`, the current one, which added the version vector, the
tombstone flag and the attributes. A cluster that was rolled forward has all
three in its logs and snapshots, because a log is append-only and a snapshot
is rewritten only when compaction happens to run.

So three things have to be true at once during a roll:

* a current node must read every layout and see current records
  (**upgrade on read**);
* a node still pinned to an older layout must keep seeing new rows
  (**dual-write** for the length of the migration window);
* and a pinned node must be served rows it can decode (**downgrade**),
  which is lossy and must say so rather than invent fields.

The module that does this is `atlas.evolution`. It takes its knowledge of
the layouts from the generated `atlas.tables.LAYOUTS`, which takes it from
`schema/tables.json`. That chain is the point of this document.

## Why on-read and not rewrite

A rewrite is a second migration hidden inside the first: it touches every
segment, it has to be resumable, and a crash in the middle leaves a log that
is half one layout and half another with no marker between them. Upgrading
on read touches nothing. The old bytes stay old, the reader does the work on
the way in, and the day the last pinned node is gone the shadow frames stop
being written and nothing else changes. `ADR-0010` has the full argument.

## Why the codec is frozen

Every frame is `atlas.codec.encode(kind, payload)`: a header, a checksum and
the **canonical** JSON of the payload — sorted keys, tight separators,
non-ASCII preserved, floats as Python repr. A `v1` row carries its value as
canonical text *inside* the payload, so the canonical form is written twice
over into history. Change it in any way — a separator, `ensure_ascii`, the
key order, the float format — and every legacy frame on disk stops matching
what a downgrade produces, every golden under `schema/goldens/` stops
verifying, and the error you see is

```
CodecMismatch(records-v1, expected=<sha256>, actual=<sha256>)
```

which is **the same error an unfinished downgrade produces**. The message
cannot tell you which of the two you did. The procedure can: the goldens are
pinned, the codec is frozen, so a `CodecMismatch` always means the evolution
code is wrong, never that the codec needs adjusting. If you find yourself
editing `codec.canonical` to make a digest match, stop; that path has been
walked and it is recorded as a dead end in `ADR-0011`.

## Why downgrade is allowed to lose

A `v1` reader has four fields. It cannot be given a vector or an attribute,
and pretending otherwise — stuffing them into the value, say — produces a row
that a real `v1` writer would never have written and that a `v1` reader may
reject. The contract (`SPEC.md` 10.6, `ADR-0013`) is therefore an exact one:
a downgraded row is *what a writer of that layout would have written*, the
same fields and no others, and the round trip up and back is byte-identical
for any frame that began in the older layout. What began at `v3` and goes
down does not come back whole, and nothing in the store claims it does.

## The procedure

This is the only place the procedure is written down. It applies to **every**
change to `schema/tables.json` — a new column, a new index, a declared
layout, a changed limit — and it is not complete until its last line passes.

1. Edit `schema/tables.json`. Nothing else is edited by hand: not
   `src/atlas/tables.py`, not `schema/MANIFEST`, not `schema/goldens/`.

2. Regenerate and lock:

   ```
   python tools/gen_tables.py --lock
   ```

   This rewrites `src/atlas/tables.py` from the document and writes
   `schema/MANIFEST` with the schema version, the generator version, and the
   sha256 of both the document and the generated module.

3. Verify the goldens:

   ```
   python tools/verify_goldens.py
   ```

   Every line must read `OK <name> <sha256>`. A `GoldenMismatch(...)` means
   the code does not reproduce what the golden pins — fix the code, never the
   golden. A `NotImplemented(...)` means the family is still a stub. When the
   change *adds* an artefact — a new index, say — record its golden once, from
   the code, and only after the code is right:

   ```
   python tools/verify_goldens.py --write index-<name>
   ```

   The rows every golden is computed from are `schema/goldens/rows.json`.
   They are fixed. A golden that does not match is never fixed by editing
   the rows.

4. Confirm the lock and commit the three together — document, generated
   module, `MANIFEST` — plus any golden you recorded:

   ```
   python tools/gen_tables.py --check
   ```

   It exits 0 only when `tables.py` is exactly the generator's output and
   `MANIFEST` records exactly those digests. A tree that fails this check has
   a hand edit in it somewhere, and the hidden acceptance tests of any task
   touching the schema run this check themselves.

The order matters. Locking before verifying is harmless; verifying before
locking is not, because a golden recorded from an unregenerated module pins
the wrong bytes. `python -m atlas.tables` is a drift *report* and writes
nothing, whatever its `--write` flag says; it is kept because scripts call it.

## Where things live

| Artefact | Path | Produced by |
| --- | --- | --- |
| schema document | `schema/tables.json` | a person |
| generated tables | `src/atlas/tables.py` | `tools/gen_tables.py --lock` |
| lock | `schema/MANIFEST` | `tools/gen_tables.py --lock` |
| golden rows | `schema/goldens/rows.json` | fixed |
| golden digests | `schema/goldens/GOLDENS.json` | `tools/verify_goldens.py --write` |
| golden bytes | `schema/goldens/<name>.frame` | `tools/verify_goldens.py --write` |
| the feature | `src/atlas/evolution.py` | a person, against `SPEC.md` §10 |

# Implement schema evolution for a sharded store

Atlas is a sharded, replicated, fenced key-value store. Its write, read,
recovery, and rebalance paths are complete, and `PYTHONPATH=src python -m
pytest tests` is green. One feature is declared and not implemented:
**schema evolution** of stored rows.

`src/atlas/evolution.py` holds the contract as a stub. Every function that
would do work raises `NotImplementedError`, and the module docstring says so.
The contract is in `SPEC.md` section 10; the procedure that accompanies any
change to the schema is in `docs/schema-evolution.md`; the decisions behind
both are in `docs/adr/`. Implement against that text, not against the stub,
and read the documentation in that order: the ADRs decide, the SPEC states,
the README is a map and is allowed to be behind.

The feature is three layouts and the paths between them. A stored row has a
layout, the set of payload fields its frame carries. The writer emits the
layout the schema document calls version 3. Two older layouts exist in
clusters that were rolled forward:

* `v1`, the legacy flat layout: `key`, `value`, `gen`, `lsn`, where the
  value is JSON *text* and a `null` value is a tombstone;
* `v2`: `v1` plus `at` and `writer`, with a JSON value;
* `v3`, the current layout: `v2` plus `vec`, `deleted`, `attrs`.

The rules that matter are in `SPEC.md` section 10, numbered so a failure can
name the clause it breaks:

* **10.2** the layouts are declared in `schema/tables.json` and reach the
  code only through the generated `atlas.tables`; the seed declares none yet;
* **10.3** detection of a payload's layout is total;
* **10.4** a row written under an older layout is upgraded **on read**; the
  bytes on disk are never rewritten;
* **10.5** during a migration a window **dual-writes**: every write is
  persisted at the current layout and at the layout a pinned reader
  understands, and the current reader notices nothing;
* **10.6** a reader pinned to an older layout is served **downgraded** rows,
  and a downgraded row must be what a writer of that layout would have
  written;
* **10.7** a legacy frame that goes up to the current layout and back down
  comes back **byte for byte**; a difference is reported as a stable
  `CodecMismatch(...)` and never as a traceback;
* **10.8** every step is registered in the strategy registry, once;
* **10.9** a change to the schema document is not done until the generated
  module and its lock and the goldens agree, by the repository's own tools.

Two things are easy to get wrong here and both are documented. The frame
bytes come from `atlas.codec`, whose canonical form is frozen: a change to
it makes some tests pass and others fail with the very error an unfinished
downgrade produces, and the two are indistinguishable from the message alone.
And `src/atlas/tables.py` is generated: a hand edit to it is not a change, and
the hidden tests check the artefacts of the procedure, not only the behaviour
of the code.

The hidden tests read large legacy fixtures — a three-segment v1 write-ahead
log with a torn tail and a v2 snapshot of over a thousand rows — and compare
digests of what the upgrade produces. They also run the repository's tools
from the workspace root. `docs/incidents/` holds two hundred notes about the
cluster's past; none of them is about this feature.

Keep the public API, the stub's surface, the repository suite, and the
goldens' source rows intact. Do not add dependencies.

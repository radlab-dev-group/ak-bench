# Implement index projection and declare an index by generation

Atlas is a sharded, replicated, fenced key-value store. Its write, read,
recovery, and rebalance paths are complete, and `PYTHONPATH=src python -m
pytest tests` is green. The schema document, `schema/tables.json`, declares
three secondary indexes — `by_writer`, `by_lsn`, `live_only` — and the
generated `atlas.tables` carries them as data. Nothing projects them: the
functions in `src/atlas/evolution.py` that would raise `NotImplementedError`.

The contract is in `SPEC.md` section 10; the procedure that accompanies any
change to the schema is in `docs/schema-evolution.md`; the decisions behind
both are in `docs/adr/`. Read them in that order: the ADRs decide, the SPEC
states, the README is a map and is allowed to be behind.

Two things are asked, and the second is the one that is easy to leave half
done.

First, implement the projection of a declared index over a set of rows
(`project_index`, `index_frame`, `install_indexes`), as SPEC section 10
specifies it:

* an entry is the index columns followed by the primary key when the key is
  not already a column, and entries are ordered column by column;
* a `where` clause filters the rows the index covers;
* a unique index whose columns repeat refuses the projection with the
  store's `DuplicateKeyError`, naming the index and the repeated columns;
* the golden form of an index is one `CONTROL` frame produced by
  `atlas.codec`;
* every declared index is registered in the strategy registry under
  `index:<name>`, once.

Second, declare a fourth index: `by_generation`, over `(generation, key)`,
not unique, no predicate. An index is declared in the schema document and
nowhere else; it reaches the code through the generated module, and a
schema change is not done until the artefacts the procedure names agree —
the generated tables, their lock, and a golden for the new index, each
produced by the repository's own tools. The hidden tests check those
artefacts as well as the behaviour, and they check them the way the tools
do, not the way a reader of the generated module would.

`src/atlas/tables.py` says at its top that it is generated. Believe it: a
hand edit there is the shape of failure this task is built around. The
frame bytes come from `atlas.codec`, whose canonical form is frozen; the
goldens pin it and a change to it is reported, not tolerated.

`docs/incidents/` holds two hundred notes about the cluster's past; none of
them is about indexes. Keep the public API, the stub's surface, the
repository suite, and the goldens' source rows intact. Do not add
dependencies.

# Implement provenance for a sharded store

Atlas is a sharded, replicated, fenced key-value store. Its write, read,
recovery, and rebalance paths are complete, and `PYTHONPATH=src python -m
pytest tests` is green. One feature is declared and not implemented:
**provenance**.

`src/atlas/lineage.py` holds the contract as a stub. Every method that would
do work raises `NotImplementedError`, and the class docstring says so. The
contract is in `SPEC.md` section 9 and the reasoning is in
`docs/lineage.md`. Implement it against that text, not against the stub.

The feature is a graph. A **node** is a key at a generation on a replica, and
an **edge** says that one node exists because of another. There are exactly
five edge kinds, and no sixth may be invented:

* `caused_by` — a write that read a prior generation of the same key;
* `replicated_by` — a quorum write that landed on a second replica;
* `repaired_by` — repair or anti-entropy wrote a peer's version forward;
* `migrated_by` — a rebalance moved the record to a different replica;
* `restored_by` — recovery applied the record from the log after a restart.

The rules that matter are in `SPEC.md` section 9, and each is numbered so a
failure can name the clause it breaks:

* **9.2** an edge is its endpoints and its kind; recording the same edge
  twice is one edge, and `LineageGraph.add` returns `False` for a duplicate;
* **9.3** a write that read nothing is a root and records no `caused_by` edge;
* **9.4** the store calls the recorder and passes the version the writer read
  as the cause; the recorder derives the edge, the store does not construct
  one;
* **9.5** `why` and `whence` stay consistent: an edge appears in exactly one
  `why` and exactly one `whence` per endpoint;
* **9.6** `trace` walks causes oldest first, with no node repeated, and
  terminates on a cycle; `export` orders by LSN then by node identity;
* **9.8** with `lineage_enabled = false` the store must not call the
  recorder, and no other behaviour may change;
* **9.9** the recorder reads no storage. It is given facts and draws a graph;
  a lineage bug must not be able to change what the store writes, reads,
  repairs, or recovers;
* **9.10** at `max_edges` the recorder stops recording and returns `None`; it
  never evicts an edge already in the graph.

The store already has a seam: `Atlas.enable_lineage(recorder)` and a private
`_record_lineage` that calls `record_write` on every accepted write. The
recorder's `record_write` is the only method the store calls for the write
path; the other four `record_*` methods are for the paths that move a version
between replicas or rebuild it from the log, and the hidden tests exercise
them by calling them directly, because those paths do not have a single call
site in the store.

`docs/incidents/` holds two hundred notes about the cluster's past. The one
that matters for this feature is not in the corpus, because the feature is
new, and the note that would mislead you — a fix that was tried and reverted,
in a different cluster, on a different feature — is in there, and it is not
about provenance. Read `docs/lineage.md` instead.

Keep the public API, the stub's surface, and the repository suite intact. The
feature is an observer: it changes nothing the store does, and a bug in it
must not be able to change anything the store does.

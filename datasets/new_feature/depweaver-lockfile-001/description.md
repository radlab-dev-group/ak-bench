# Implement the reproducible lockfile for an offline dependency resolver

Depweaver is an offline semantic-version dependency resolver: features,
environment markers, partial lock updates, conflict learning, backjumping, a
checksummed lockfile, a replaying session and a content-addressed artifact
store. All of that is complete, and `PYTHONPATH=src python -m pytest tests` is
green. One feature is declared and not implemented: the **reproducible
lockfile** — a canonical form with a digest, a proof of solution that is
verified offline, and proof-driven invalidation of cached resolutions.

`src/depweaver/canonical.py` and `src/depweaver/proofs.py` hold the contract
as stubs; every function that would do work raises `NotImplementedError`, and
so do `Store.remember`, `Store.recall` and `Store.invalidate` in
`src/depweaver/store.py`. The contract is `SPEC.md`, section "Lockfile
canonical form and proofs", clauses C1–C6 and P1–P8. Implement it against that
text, not against the stubs. Where documents disagree, `CONTRIBUTING.md`
states which one is right.

## Symptoms the feature must remove

* Two builds from the same manifest against the same catalog, exported by two
  different tools, produce two different lock digests while `depweaver diff`
  reports no difference. The digest must depend on *what was solved*: the
  order metadata was declared in, the quoting and operand order of markers,
  and build metadata on versions must not change it; a changed selection, a
  changed active extra or a changed target must.
* A lockfile can only be checked by re-running the solver. It must instead be
  checkable from a compact **proof of solution** — the chosen releases, the
  catalog digest and one justification clause for every catalog version the
  policy would have preferred — without constructing a `Resolver`.
* The artifact store hands back a cached resolution for a manifest long after
  the catalog it was solved against has moved. A cached resolution whose proof
  no longer verifies under the catalog the caller presents must be removed,
  never returned.

## What the hidden tests check

* the canonical form is equal across permuted, re-spelled and build-tagged
  catalogs, and its digest matches goldens produced by the reference, for a
  five-package example, a dependency cycle and a generated catalog with sixty
  selected packages;
* the canonical **order** is the one the documentation specifies. It is not
  the alphabetical order the lockfile body uses, and the guide in `docs/`
  explains why. A proof whose `chosen` list is alphabetical is rejected;
* proofs are generated for a resolution and verified offline, round-trip
  through the codec, and are rejected with `ProofInvalid(hash=..., reason=...)`
  for three different causes that share the same exception type, the same
  hash and the same message shape: a wrong canonical order, a stale catalog
  digest, a missing justification clause. The tests distinguish the causes
  by the reason; a fix that addresses only one of them fails the next test
  with an identical-looking error;
* `Store.recall` and `Store.invalidate` drop entries whose proof fails under
  the current catalog and keep the others;
* the procedure: `tools/relock.py --canonical --prove` must print the golden
  digest and write a proof that `tools/verify_lock.py --expect <digest>`
  accepts; skipping `--canonical --prove` is a stable error, not a pass.

## Where the truth is

`docs/adr/ADR-0001` to `ADR-0004` record why the order is what it is, why
proofs are verified offline, why the catalog digest is part of the proof and
why `ProofInvalid` carries one hash and one reason. `docs/incidents/` holds
the three incidents, written by symptom, that produced those decisions.
`docs/lockfile-canonical-form.md` is the guide: the exact ordering rules, the
marker rule, the check order and the playbook. `README.md` does not mention
any of this; that is a known gap, not a hint.

Keep the public API, the stubs' surface, the tools' command lines and the
repository suite intact. Do not touch the solver modules: the feature reads
resolutions and catalogs, it does not search.

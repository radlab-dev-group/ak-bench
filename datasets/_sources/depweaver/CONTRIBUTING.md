# Contributing to depweaver

## Hierarchy of truth

When two documents disagree, the one higher in this list is right and the
lower one has a bug to be filed:

1. `docs/adr/` — architecture decision records. Each records one decision,
   why it was taken and what was rejected. They are never edited after
   acceptance; a change is a new ADR that supersedes the old one.
2. `SPEC.md` — the normative contract: what the code must do, numbered so a
   failing test can name the clause it breaks.
3. `README.md` — orientation. It is allowed to lag. It currently says nothing
   about canonical forms or proofs of solution, and that is a known gap, not a
   statement that the feature does not exist.

`docs/*.md` guides (such as `docs/lockfile-canonical-form.md`) explain SPEC
clauses with examples and procedures; they rank with SPEC.md and below the
ADRs. `docs/incidents/` are history: they explain *why* an ADR exists, by
symptom, and are not themselves normative.

## Procedures

* Run the suite from the repository root: `PYTHONPATH=src python -m pytest tests`.
* Lockfiles that are checked in are produced with `tools/relock.py --canonical
  --prove` and checked with `tools/verify_lock.py`. A lockfile without a proof
  next to it is not considered reproducible. The procedure, including what
  each tool prints and which value to keep for the final check, is in
  `docs/lockfile-canonical-form.md`.
* Standard library only. No third-party packages in `src/`, `tools/` or
  `tests/`.

## Changing the contract

* A behavioural change to anything in `SPEC.md` needs an ADR first.
* Public surfaces (module-level functions, dataclass fields, exception
  attributes, tool exit codes and output lines) are compatibility surfaces.
  Add; do not rename or remove.
* Declared-but-unimplemented surfaces (functions that raise
  `NotImplementedError` and say so in their module docstring) are implemented
  against `SPEC.md` and the ADRs, not against the stub.

# Reproducibility

AK-Bench does not promise identical agent answers: a model is not a function,
and asserting otherwise would make a benchmark out of a coin flip. What it
does promise is that the **conditions** of an experiment are identical and that
the record of those conditions is complete enough to prove it after the fact.

## What "the same conditions" means

A run is reproducible when a reader can verify, from the history alone:

- which **experiment** it belonged to, and which **variant** of its matrix;
- which **descriptors** it used, and that they were the pinned versions — the
  pinned payloads are stored, not just their digests, so "the descriptor
  changed" is not the only conclusion available;
- which **task version** it ran, and that the task resolves to the same digest
  as when it ran;
- which **agent, runtime and mode** it used;
- what **configuration hash** the variant carried;
- what the **plugins** reported, with their verification status, and what the
  router reported about the **model**;
- that its **artifacts** are still the files it produced: each artifact row
  carries a checksum, and `akbench history verify RUN` recomputes it.

The **reproducibility manifest** (see `docs/STORAGE.md`) is the compact form
of the first five: one digest, derived only from what was stated, with every
unstated field listed in `unknown_fields` rather than guessed.

## What is deliberately not asserted

- that two runs produce the same **verdict** — a verdict is a measurement, and
  measurements vary;
- that two runs use the same **model output** — a router can route the same
  request differently, and the history records what was observed, with the
  verification status that observation deserves.

## Where the guarantees are tested

- `tests/unit/test_reproducibility.py` — the same plan built into two histories
  is indistinguishable in everything a reproduction is defined by; a changed
  pinned descriptor shows up; repeated recording does not fork the history;
  artifact verification is a check a reader can repeat.
- `tests/e2e/test_yaml_to_report.py` — one experiment file through plan, runs,
  history, report and export, with the manifests and the failure path intact.

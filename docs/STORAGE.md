# Storage

The project's state lives in one SQLite database, created and migrated by
`akbench init`. This page describes the layout, the history model added in
phase 11, and the rules that keep a recorded result honest.

## History of experiments (phase 11)

The database is the single history of everything the project did. The tables
that make a result re-readable are the ones a report later needs:

- `experiments`, `experiment_variants`, `benchmarks`: what was planned, and
  what it cost in runs;
- `tasks`, `repositories`, `datasets`: the exact task versions and the
  repositories they came from;
- `task_runs`, `evaluations`, `plugin_observations`, `agent_observations`,
  `model_observations`: one row per run, per verdict, per plugin state, per
  token count;
- `descriptor_snapshots`: the full payload of every descriptor a plan pinned,
  next to its digest;
- `metrics`, `experiment_metrics`: the catalog as observed, and the aggregates
  computed from it;
- `events`: the lifecycle, plus warnings such as a run citing a task the
  history has never seen.

### What stays on disk

Traces and the evaluator's raw output are not copied into the database: the
row keeps the path, and the path is only a pointer because the checksum is
stored next to it. `artifacts` therefore carries `checksum`, `size_bytes`,
`kind` and `content_type`, and `task_runs.manifest_digest` ties the row to the
reproducibility manifest written to `manifest.json` in the run's artifact
directory.

### The reproducibility manifest

`akbench/storage/manifest.py` builds, per run, the identity of what it was:
experiment and variant, task version and repository commit, agent version,
adapter, runtime, plugin versions, descriptor digests and the configuration
hash. A field that was never observed is `None` and is listed in
`unknown_fields`; `complete` is true only when every required field is stated.
The manifest's digest is derived from those facts alone, so a run can cite it
and a later reader can check that the cited run was what it claimed to be.

### Verification

`akbench history verify RUN` re-checksums every artifact of the run against
what `artifacts` recorded, and exits non-zero on a mismatch. A run whose
`run_record.json` was edited after the fact is not a history entry anymore;
the command says so instead of pretending.

### Recording

`akbench experiment plan FILE --store` records the plan itself: the
experiment, its variants with configuration hashes, the pinned descriptors
with their payloads, and the metric catalog the plan declares. A run is
recorded by `akbench run single --store`, which also writes the manifest,
observes the plugin state, registers the artifacts and appends an event.
Both are idempotent: re-planning or re-recording updates the existing rows
rather than forking the history, and a value that was never measured is
stored as `NULL`, never as zero.

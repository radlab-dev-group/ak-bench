# Storage

The project's state lives in one database — PostgreSQL by default, a SQLite
file when `database.backend: sqlite` is configured — created and migrated by
`akbench init`. The connection parameters of the default backend come from the
project `.env` (`AKBENCH_PG_*`, the names `scripts/run-postgres.sh` reads);
`database.url` pins a full SQLAlchemy URL over both. This page describes the
layout, the history model added in phase 11, and the rules that keep a recorded
result honest.

## Namespaces: many histories, one server

A working directory has exactly one history, so two of them cannot share one
schema: they would collide on the first primary key. PostgreSQL keeps them
apart with schemas, one per imported SQLite file:

```bash
akbench migrate sqlite data/akbench.sqlite          # → namespace `akbench`
akbench migrate sqlite /other/project/data/akbench.sqlite
akbench migrate list                                # every namespace, its runs, its revision
```

A namespace is read back by naming it:

```bash
export AKBENCH__DATABASE__POSTGRES__NAMESPACE=akbench
akbench history experiments
```

The import is the same copy the platform has always trusted: the tables come
from the Alembic revisions, children land after their parents, every table is
counted on both sides, and a difference is an error. The only translation is
time: SQLite stores a UTC instant without its offset, so it is re-anchored to
UTC on the way in -- letting PostgreSQL read it as local time would move every
recorded run.

## History of experiments (phase 11)

The database is the single history of everything the project did. The tables
that make a result re-readable are the ones a report later needs:

- `experiments`, `experiment_variants`, `benchmarks`: what was planned, and
  what it cost in runs;
- `tasks`, `repositories`, `datasets`: the exact task versions, what they ask
  (title, description, the full `task.yaml` and the task's `description.md`)
  and the repositories they came from;
- `task_files`: the code a task is made of — the repository it is worked in,
  its hidden and public tests and its mutation patch — one row per file with a
  `kind`, `size_bytes` and a `sha256` digest, so a task's code can be read
  from the history without the dataset checkout (migration `0010`);
- `agents`, `runtimes`: every agent and runtime version a run was made of,
  keyed by the id a run already carries, each with the descriptor file it
  declared; `experiments.experiment_yaml` is the experiment's own descriptor;
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
adapter, runtime, plugin versions, descriptor digests, the declared environment
(identity, sandbox kind and the descriptor's digest, alongside `sandbox_image`
when the environment names an image) and the configuration hash. A field that was never observed is `None` and is listed in
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

Recording a run also records the task's own content — the title, the
one-line description, the descriptor as written and the task's
`description.md` — and the task's *code*: the repository it is worked in,
its hidden and public tests and its mutation patch, file by file. A file
that cannot be shown is not recorded as an empty one — binary content and
files over 256 KB are skipped, and a task that did not come from a
directory (a test stub) records no files at all — so what is stored is
always what a reader would be handed. The same applies to the components a
run was made of: the experiment's descriptor, the agent and the runtime,
each kept per `(id, version)` with the file it declared.

A history built before these columns and tables existed is backfilled from
the dataset on disk with `scripts/update_task_info.py`, which migrates the
schema to head first and reports, per task row, which columns it filled and
how many files it recorded.

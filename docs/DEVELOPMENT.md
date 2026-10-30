# Development environment

## 1. Setup

```bash
uv venv --python 3.12 .venv          # the system Python is 3.10 — not enough
uv pip install -e ".[dev]"
akbench init
akbench doctor
```

`uv` is not required by the package, but this machine has no Python 3.12 and
`requires-python` is `>=3.12`. Any `venv` on Python 3.12 works as well.

## 2. Tests and linting

```bash
.venv/bin/python -m pytest -q          # everything
.venv/bin/python -m pytest tests/unit -q
.venv/bin/ruff check src tests
.venv/bin/ruff check src tests --fix
```

Tests need neither network nor an agent: they run against temporary
directories, real local git repositories and SQLite files. Integration tests
 (the CLI) use `typer.testing.CliRunner`.

Contract tests worth knowing about:

- `tests/unit/test_migrations_match_models.py` — compares the schema produced
  by the migrations with `Base.metadata` through
  `alembic.autogenerate.compare_metadata`. A migration that drifts from the
  models breaks this test.
- `tests/integration/test_cli.py` — exit codes and the shape of `--json`
  output.
- `tests/unit/test_descriptor_registry.py` — discovery, versioned identity,
  digest stability and conflicts; also asserts that every shipped descriptor
  still loads (and that unavailable metrics carry a reason).
- `tests/unit/test_env_observation.py` — the ENV allowlist: only declared
  variables are read, secrets are reduced to `is_set`.
- `tests/integration/test_workspaces.py` — git worktree workspaces and mutation
  verification against real repositories (repeatable fingerprints, cleanup,
  hidden-test isolation, `not_detectable` rejection).
- `tests/integration/test_dataset_cli.py` — the dataset command group.

## 3. Migrations

The Alembic scripts live **inside the package**
(`src/akbench/storage/migrations/`), so they work after `pip install` without
an `alembic.ini`. Programmatic entry point: `akbench.storage.migrator`.

Because `script_location` points into the package, in practice you add a file
under `versions/` following `0001_core_tables.py`, then run `akbench init`
(which applies migrations) and the contract test above.

Rules:
- SQLite with `render_as_batch=True` (the `ALTER TABLE` limitations),
- `task_uid` in `task_runs` is a plain string for now — the real foreign key to
  `tasks` arrives in Phase 3,
- `task_runs.task_uid` is a real foreign key to `tasks.uid` from Phase 3 on, so
  a run can never reference a task that was never registered;
- the complete data model (metrics, observations, descriptor snapshots,
  events) lands in Phase 11.

## 4. Code conventions

- Python 3.12 (PEP 695 generics), `from __future__ import annotations`, every
  signature typed.
- Exceptions from `akbench.core.errors` carry a `failure_class` — an
  infrastructure error must never look like an agent error (plan rule 11).
- Agent names (for example `codex`) never appear in the generic runner,
  scheduler or evaluator; external tools are configured through
  `doctor.required_tools`.
- `--json` writes pure JSON to stdout (not through rich, which wraps lines
  inside strings); logs go to stderr. This keeps
  `akbench doctor --json | jq` working, including with `2>&1`.
- Line length 100 (`ruff`, `E501`).
- **Language:** code, comments, docstrings, documentation and commit messages
  are English. Only `.plans/` is Polish.

## 5. Deliberately unfinished

- The `runtime`, `experiment`, `report` and `export` commands — Phases 4 and
  later.
- The runtime and plugin *adapters* that act on the runtime/plugin descriptors
  (configuration read/write, verification, event interpretation) — Phases 5
  and 9. Until then the descriptors describe the interface; nothing acts on it.
- The Agent Adapter Framework (the universal contract + the Codex adapter) —
  Phase 4.
- The evaluator *engine* that runs hidden tests against an agent's produced
  workspace — Phase 6 (the dataset layer only verifies mutations today).
- The observability and metrics layer — Phases 9 and 11.
- Docker sandboxing — Phases 3/7 (Docker availability verified, not implemented).

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
directories and SQLite files. Integration tests (the CLI) use
`typer.testing.CliRunner`.

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

- The `dataset`, `runtime`, `experiment`, `report` and `export` commands —
  Phases 3 and later.
- The runtime and plugin *adapters* that act on the runtime/plugin descriptors
  (configuration read/write, verification, event interpretation) — Phases 5
  and 9. Until then the descriptors describe the interface; nothing acts on it.
- The `tasks` table and its relations — Phase 3.
- The observability and metrics layer — Phases 9 and 11.
- Docker sandboxing — Phases 3/7 (Docker availability verified, not implemented).

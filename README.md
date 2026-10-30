# AK-Bench

**Agentic Knowledge Benchmark** — an extensible platform for repeatable
evaluation of coding agents, LLM routers, models, and the plugins that extend
their capabilities (knowledge bases, routing, optimizations).

Overriding principle: **the agent under test is a replaceable component**.
AK-Bench does not implement an agent, a memory, or routing. It orchestrates
task execution through a chosen agent and verifies the outcome independently.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Integration spike (Codex CLI + LLM Router) | done |
| 1 | Skeleton: CLI, configuration, logging, SQLite, migrations | done |
| 2 | Descriptors and registries | done |
| 3 | Dataset, tasks, repositories, workspaces | done |
| 4 | Agent adapter framework | next |

The full plan lives in `.plans/AK-Bench-implementation-plan.md` (Polish).

## Requirements

- Python 3.12+ (easiest through [`uv`](https://docs.astral.sh/uv/))
- Git
- Docker — optional, only for sandboxing runs

## Quick start

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"

akbench init          # directories + configuration + database (migrations to head)
akbench doctor        # environment readiness
akbench config show   # effective configuration and paths
akbench descriptor validate  # component descriptors
akbench dataset validate     # tasks (add --verify-mutations to prove defects)
```

## Commands

| Command | Description |
|---|---|
| `akbench version [--json]` | AK-Bench version and key dependency versions |
| `akbench init [--json] [--force-config] [--no-migrate]` | create directories, configuration and schema |
| `akbench doctor [--json] [--strict]` | environment diagnostics; exit 1 on failures |
| `akbench config show [--json] [--all]` | effective configuration, paths, database URL |
| `akbench config validate` | validate the configuration file without writing |
| `akbench descriptor list [--kind K] [--json]` | list registered descriptors |
| `akbench descriptor validate [--kind K] [--json]` | validate every file; exit 1 on any failure |
| `akbench descriptor show REF --kind K [--json]` | one descriptor: content, digest, derived facts |
| `akbench agent list [--json]` | registered agents with usable-capability counts |
| `akbench agent inspect REF [--json]` | agent capabilities, statuses, controllable parameters |
| `akbench category list [--json]` | task categories and whether they are enabled |
| `akbench dataset list [--category C] [--json]` | registered tasks |
| `akbench dataset validate [--check-repositories] [--verify-mutations] [--json]` | validate tasks; exit 1 on failure |
| `akbench dataset show REF [--json]` | one task with its resolved repository and digest |
| `akbench dataset prepare REF [--no-mutation] [--json]` | create a repeatable workspace for a task |

Global options: `--config/-c`, `--project-root`, `--verbose/-v`, `--quiet/-q`, `--version`.

## Configuration

`configs/defaults.yaml`, overridable through `AKBENCH__SECTION__FIELD`
environment variables:

```bash
export AKBENCH__LOGGING__LEVEL=DEBUG
export AKBENCH__DATABASE__URL=sqlite:////tmp/akbench.sqlite
```

Configuration lookup: `--config` → `AKBENCH_CONFIG` →
`<project root>/configs/defaults.yaml` → built-in defaults.
Project root: `AKBENCH_HOME` → the nearest ancestor whose `pyproject.toml`
declares the project name `ak-bench` → the current directory.

Unknown keys are rejected: an option that is silently ignored looks effective
while it is not.

## Layout

```text
src/akbench/
  cli/          # CLI layer (typer)
  config/       # Pydantic models + YAML/ENV loading
  core/         # errors, paths, time, logging
  descriptors/  # descriptor models, ENV allowlist, registry
  storage/      # SQLAlchemy, models, Alembic migrations, migration runner
  datasets/     # task descriptors, dataset validation, repositories, workspaces
  bootstrap.py  # `akbench init` logic
  doctor.py     # environment diagnostics
tests/
  unit/         # paths, configuration, storage, doctor, descriptors
  integration/  # CLI
descriptors/    # component definitions (agents, plugins, models, ...)
datasets/       # task definitions, hidden tests and mutation patches
data/           # run directories, repository cache and database (git-ignored)
docs/           # integration and development documentation
spike/          # Phase 0 code (flow validation)
```

## Documentation

- `docs/AGENT_INTEGRATION.md` — verified Codex CLI capabilities, including what
  its interface does **not** provide (cost, cancellation, session reset)
- `docs/ROUTER_INTEGRATION.md` — LLM Router: healthcheck, models, plugins,
  metrics and verification limits
- `docs/DESCRIPTOR_SYSTEM.md` — descriptor kinds, registries, ENV allowlist, dimension rules
- `docs/DATASETS.md` — tasks, repositories, repeatable workspaces, mutation verification
- `docs/DEVELOPMENT.md` — development environment, tests, migrations

## Conventions

Code, comments, docstrings, docs and commit messages are in English. Only the
implementation plan (`.plans/`) is written in Polish.

## License

MIT — see `LICENSE`.

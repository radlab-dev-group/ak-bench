# AK-Bench

**Agentic Knowledge Benchmark** — an extensible platform for repeatable
evaluation of coding agents, LLM routers, models, and the plugins that extend
their capabilities (knowledge bases, routing, optimizations).

Overriding principle: **the agent under test is a replaceable component**.
AK-Bench does not implement an agent, a memory, or routing. It orchestrates
task execution through a chosen agent and verifies the outcome independently.

## Requirements

- Python 3.12+ (easiest through [`uv`](https://docs.astral.sh/uv/))
- Git
- Docker — optional, only for sandboxing runs

## Quick start

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"

akbench init                    # directories + configuration + database (migrations to head)
akbench doctor                  # environment readiness
akbench config show             # effective configuration, paths, database
akbench descriptor validate     # component descriptors
akbench dataset validate        # tasks (add --verify-mutations to prove defects)
```

Recorded benchmarks go to a **SQLite file** by default — `data/akbench.sqlite` —
so a fresh clone runs with no server, no credential and no `.env`. The shared
mode is **PostgreSQL**, chosen on purpose with
`AKBENCH_DB_BACKEND=postgres` plus the `AKBENCH_PG_*` names; for a local
instance `scripts/run-postgres.sh start` starts the container that reads them,
and the engine and the script read the same names, so one `.env` drives both.

The `data/` directory is local, untracked and safe to delete at any time:
workspaces, artifacts, runtime instances and the SQLite file are all created
on demand by `akbench init` and `doctor`. Historical data that used to live
in the sibling `ak-bench-data` repository is imported per namespace with
`akbench migrate sqlite …` (see ``akbench migrate --help``).

Several working directories can share one server: each SQLite history is
imported into its own namespace and read back by naming it
(``akbench migrate sqlite …`` / ``akbench migrate list``).

## How AK-Bench reads a configuration

Three kinds of file drive everything the platform does, and each answers a
different question. Reading them in this order explains every behaviour the rest
of this document assumes.

| File | Question it answers | Read by |
|---|---|---|
| `configs/defaults.yaml` | where things live, which database, how loudly to log | `akbench` on every command |
| `descriptors/**.yaml` | what exists, and what can be proven about it | registries, the planner, adapters |
| `configs/experiments/**.yaml` | what to measure, in which combinations | `experiment validate/plan/run` |

Nothing outside these files is configuration: an environment variable that the
platform does not name in a descriptor is never read, and a component without a
descriptor cannot be measured.

### Settings

`configs/defaults.yaml` holds paths, the database, logging and the `doctor`
requirements. Override any value with `AKBENCH__SECTION__FIELD`, select the file
with `--config` or `AKBENCH_CONFIG`, and the project root with `AKBENCH_HOME` or
`--project-root`. Unknown keys are rejected at load time, so an option that
would be silently ignored is an error instead.

### Descriptors: what exists, and what can be proven

`descriptors/` carries one file per component in eight kinds: `agent`,
`runtime`, `plugin`, `dimension`, `model`, `category`, `evaluator`, `metric`.
Each has `schema_version`, `id`, `version`, `title`, `description` and a body
named after the kind. Two rules make them more than documentation:

- **Allowlists, not scanning.** A component declares every variable it may be
  observed through (`observed_env` for plugins), with a type, a role and flags
  for `observed`, `dimension`, `controllable` and `sensitive`. AK-Bench reads
  those names and no others; a secret is recorded as presence, never a value.
- **A status travels with every reading.** One of `verified`, `unverified`,
  `mismatch`, `unsupported`, `not_configured`, `runtime_error`
  (`src/akbench/descriptors/statuses.py`). A value AK-Bench cannot confirm is
  reported with the reason it is unconfirmed, never as a zero and never as a
  guess.

Validate them before anything else: `akbench descriptor validate`.

### Experiments: what to measure

An experiment file names the agent, the execution mode and runtime, the task
selection, the factors, the policy, the evaluators and the metrics. Its blocks
(`src/akbench/experiments/descriptor.py`) are strict — an unknown key is an
error, and several invalid combinations are refused outright because they would
measure nothing: an agent failure cannot be retried, a workspace cannot be
shared between runs, `knowledge_replay` cannot drop its fresh control arm.

The planner turns one file into `tasks x variants x repetitions` and refuses the
plan, rather than degrading it, when a factor is outside a dimension's declared
value space, when a factor maps to an agent parameter that the agent does not
declare controllable, when a task's own timeout exceeds the experiment's, or
when a plugin factor is aimed at a runtime that cannot control plugins per run.
Check without executing: `akbench experiment validate FILE`, then
`akbench experiment plan FILE` to see the matrix.

### Where a factor value actually goes

A dimension's `source` decides the destination, and only that:

| `source` | Destination |
|---|---|
| `agent.configuration.<param>` | an agent parameter (`model` becomes `codex -m`) |
| `plugin.<id>.env` | the runtime process environment, through the runtime's `factor_env` map |
| `runtime.response.<field>` | observation only: the dimension is not controllable and cannot be a factor |

So a factor named after a real variable is not enough: for a plugin factor the
runtime descriptor must carry the `factor_env` line that maps the factor to that
variable, and the dimension must be declared with `source: plugin.<id>.env`.
This is the most common reason a configuration "runs but changes nothing".

### Runtime lifecycles: managed and external are different instruments

A runtime declares `supported_lifecycles`, and an experiment chooses one:

- **`managed`** — AK-Bench launches the process from the descriptor's `managed`
  block (`command`, `cwd`, `env`, `factor_env`, `config_file`, `ready_timeout`,
  `stop_grace`, `log_file`) and stops it when the run ends. Environment
  precedence, lowest to highest: the ambient environment, `managed.env`, the
  factor-mapped values, then the arm's own `runtime_env`. A managed run must own
  its endpoint: if something already answers the configured `base_url`, the
  start is refused and the task never begins, because a healthcheck passing on a
  foreign process would measure an instance the run does not control.
- **`external`** — a shared instance: AK-Bench only ever observes it. It never
  starts, stops or reconfigures it, and a plugin toggle against it is recorded as
  requested, not applied (`unsupported` where no read path exists).

An experiment that needs a configuration applied rather than requested runs
managed. That difference is a property of the plan, not of the runtime software.

### Plugins: loading, enabling and verifying are three separate facts

- **Loading** is decided when the process starts, from
  `LLM_ROUTER_UTILS_PLUGINS_PIPELINE`, so an arm declares it under its own
  `runtime_env`. A pipeline in the runtime descriptor's static `env` would load
  those plugins in every arm of the runtime, which is why the shipped managed
  descriptor declares none.
- **Enabling** is a toggle, and `benchmark.enabled_when` names it. That variable
  must be one of the descriptor's allowlisted entries. A plugin with no toggle
  cannot report `enabled` honestly: it is reported `false` with a note that
  activation is not observable.
- **Verifying** needs evidence the platform does not always have. A run records a
  plugin row only for a plugin it engaged — named in the pipeline it started its
  process with, or with its own toggle set. Rows are not emitted for plugins of
  the installation that the run said nothing about.

```yaml
# An arm that loads the routing plugin and asks for knowledge, against an
# instance this run starts and owns.
combinations:
  - model: auto_codex
    knowledge_enabled: true
    runtime_env:
      LLM_ROUTER_UTILS_PLUGINS_PIPELINE: agentic_routing_codex,agentic_knowledge
```

### From one run to one report row

Each run walks the lifecycle in `src/akbench/orchestration/lifecycle.py`, from
`pending` to one terminal state: `completed`, or one of `failed`, `timeout`,
`cancelled`, `infrastructure_error`, `invalid_configuration`,
`evaluation_error`. It leaves behind a record (`state`, the transition
`history`, `runtime_environment`, `served_models`, `model_evidence`), its
artifacts (`router.log`, the agent's own trace, the diff, the evaluation output)
and a row in the history database. `akbench report all` renders that history as
static HTML, and its "Not verified" table is the list of rows whose status is
not `verified` — a run under them is only as trustworthy as they are.

Model verification is read from the instance's own log of a process the run
started (`src/akbench/runtime/llm_router.py`): the models it received, the
routing decision and the model each request was forwarded to. A requested model
the log names is `verified`; an alias is verified as an alias, with the resolved
model recorded; a model the log never names is a `mismatch`. A model inventory
from `GET /v1/models` says what an instance *can* serve, so it can never verify
the pairing on its own.

Every view that names what a run was configured as uses one label for it
(`bench_ui/service.py:configuration_label`): the model the run asked for, then
each plugin that was **on**, then the models that served it in brackets when
those are not simply the name already there.

```text
qwen/Qwen3.8-27B                                            asked for, served
auto_codex+agentic_knowledge[qwen/Qwen3.8-27B, qwen/Qwen3.8-Flash-Next]
auto_codex+agentic_knowledge                                no log confirmed it
```

The brackets are what makes an alias readable: `auto_codex` is not a model, and
listing only the two models routing chose between hides both the alias and the
choice. A plugin that was off is not part of the label, because it described no
run — the row's own plugin list names plugins whatever their state, so the label
is built from the recorded `enabled` flag instead. Cost is still estimated from
the real model name, never from this label.

### Checking a configuration before it costs a run

```bash
akbench descriptor validate           # every component descriptor
akbench experiment validate FILE      # the plan is runnable, or why it is not
akbench experiment plan FILE          # the resulting matrix, with variants
akbench plugin status                 # how each plugin reads right now
akbench doctor                        # tools, directories, database, disk
```

`experiment run` then prints, per run, when it started, how long it took and
where the time went (`phases:`), read from the run's own transition log.

### Things that look wrong and are correct

- A plugin row `unverified` with "not set, so the process runs the plugin with
  its built-in default": the arm loaded the plugin but chose no value for it.
  The default is a configuration the run did not pick.
- No plugin row at all: the arm named no pipeline and set no toggle, so it has
  nothing to verify. That is not a defect.
- `mismatch` on the model row: the instance the run started never named that
  model in its log. Either the request never reached it, or the plugin that was
  expected to rewrite it has no log line AK-Bench knows yet.

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
| `akbench agent run REF [--task T] [--workspace D] [--runtime R] [--mode M] [--param k=v] [--json]` | run one task through an agent adapter |
| `akbench runtime list [--json]` | registered runtimes |
| `akbench runtime health REF [--json]` | healthcheck; exit 1 if down |
| `akbench runtime models REF [--json]` | served models (aliases not included) |
| `akbench runtime config REF [--config-file F] [--json]` | requested/effective/observed config with trust level |
| `akbench runtime state REF [--json]` | health, models, metrics snapshot |
| `akbench evaluate task REF --workspace D [--evaluator E] [--json]` | judge a produced workspace; exit 2 when the harness broke |
| `akbench run single TASK --agent A [--mode M] [--runtime R] [--param k=v] [--store] [--experiment E] [--json]` | orchestrate one run: prepare, execute, evaluate, record (store it in the history) |
| `akbench experiment list [--json]` | the experiment definitions under `configs/experiments` |
| `akbench experiment validate [FILE...] [--json]` | validate experiments; exit 1 when one is not runnable |
| `akbench experiment plan FILE [--variants] [--store] [--json]` | expand an experiment into tasks, variants and runs (store the plan in the history) |
| `akbench plugin list [--json]` | the plugin descriptors this project ships |
| `akbench plugin status [REF] [--env NAME=VALUE] [--json]` | observed plugin configuration, secrets as presence only |
| `akbench plugin verify [REF] [--config-file F] [--json]` | verify a plugin against available evidence |
| `akbench metrics catalog [--group G] [--json]` | the metric catalog with every metric's availability |
| `akbench metrics run RECORD [--baseline B] [--json]` | aggregate recorded runs, with baseline deltas |
| `akbench knowledge plan [FILE] [--allow-unverified] [--json]` | build the memory plan: arms, fingerprints, readiness gate |
| `akbench knowledge readiness [--session F] [--json]` | KB readiness for a replay, honestly reported |
| `akbench category list [--json]` | task categories and whether they are enabled |
| `akbench dataset list [--category C] [--json]` | registered tasks |
| `akbench dataset validate [--check-repositories] [--verify-mutations] [--json]` | validate tasks; exit 1 on failure |
| `akbench dataset show REF [--json]` | one task with its resolved repository and digest |
| `akbench dataset prepare REF [--no-mutation] [--json]` | create a repeatable workspace for a task |
| `akbench history experiments [--json]` | recorded experiments with run counts and verdicts |
| `akbench history runs [EXPERIMENT] [--json]` | recorded runs, optionally for one experiment |
| `akbench history show RUN [--json]` | one run: evaluation, artifacts, manifest digest |
| `akbench history metrics EXPERIMENT [--json]` | the recorded aggregates of an experiment |
| `akbench history verify RUN [--json]` | re-checksum the run's artifacts; exit 1 on mismatch |
| `akbench report all [--output DIR] [--json]` | write the static HTML report tree |
| `akbench report experiment UID [--output DIR] [--json]` | write the report of one experiment |
| `akbench report task UID [--output DIR] [--json]` | write the report of one task |
| `akbench experiment run FILE [--store] [--only N] [--json]` | execute the experiment's matrix and record it |
| `akbench export experiment UID [--format json\|csv\|html] [--output DIR] [--json]` | export one experiment, screened for secrets |

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

### The database

Where a recorded benchmark lives is chosen by `database.backend`:

- **`sqlite` (default)** — the file named by `paths.database_file`; a fresh
  clone records here without a server or a credential.
- **`postgres`** — the shared mode, for a database several checkouts write to.
  The parameters of `database.postgres` are the same `AKBENCH_PG_*` names
  `scripts/run-postgres.sh` reads, so the project `.env` file configures the
  helper container and the engine at once. An exported variable beats the
  file; `AKBENCH__DATABASE__POSTGRES__*` beats both.
- **`database.url`** overrides both and pins a full SQLAlchemy URL.

The URL is shown with the password redacted (`akbench config show`, the UI
footer); the connection itself is never printed.

Two things about it are deliberate:

- **`AKBENCH_PG_PASSWORD` has no default.** Building a connection without one
  raises rather than inventing one, because a credential that ships with the
  repository is a credential every installation shares. The field is a
  `SecretStr`, so dumping the settings object does not carry it either.
- **`scripts/run-postgres.sh` publishes on loopback.** `AKBENCH_PG_BIND` is
  separate from `AKBENCH_PG_HOST` because publishing a port on `0.0.0.0` while
  naming `127.0.0.1` as the host is how a database ends up reachable from a
  network its operator meant to exclude. Set `AKBENCH_PG_APP_USER` and the
  script provisions a role that is not a cluster superuser; AK-Bench needs to
  read and write its own tables and nothing more, and connecting as the
  bootstrap superuser turns any SQL access into access to the host.

## Serving the dashboard

`akbench ui` binds `127.0.0.1` and trusts whoever reaches it. That is right for
a laptop and wrong for anything else, so the dashboard reads its posture from
the environment:

| variable | default | what it decides |
| --- | --- | --- |
| `AKBENCH_UI_AUTH` | `auto` | `on`, `off`, or `auto` — authenticate unless the bind address is loopback **and** no user is configured (in the database, `AKBENCH_UI_USERS`/`_USERS_FILE`, or a proxy header). An unset address counts as exposed, not as private. Set `off` to keep a loopback instance open even with users. |
| `AKBENCH_UI_PUBLIC_READ` | `on` | `on` — results are readable without signing in and only the Admin page and its deletes need a sign-in (the answer key still needs a judge or admin); `off` — every page needs a sign-in. |
| `AKBENCH_UI_USERS` | — | `name:secret[:role],…`, roles `viewer` (default) and `judge`. |
| `AKBENCH_UI_USERS_FILE` | — | the same entries, one per line, for a secret that should not sit in `ps` or a shell history |
| `AKBENCH_UI_JUDGE_USERS` | — | names that are judges, when the proxy supplies them |
| `AKBENCH_UI_USER_HEADER` | — | trust a proxy's header (e.g. `X-Forwarded-User`) instead of HTTP Basic |
| `AKBENCH_UI_CSP` | a same-origin policy | the `Content-Security-Policy` sent with every response |
| `AKBENCH_UI_SHOW_GROUND_TRUTH` | `auto` | who may see a task's hidden tests and planted defect: `auto` (judges only when authenticated), `always`, `never` |
| `AKBENCH_UI_ARTIFACT_ROOTS` | the configured data dirs | the only directories an artifact's recorded path may be read from; test reports stored in the database are read from there first, so this only matters for artifacts registered without their content |

Authentication on with nobody configured is a startup error on the command line
and a 503 from a served app: a gate with nobody behind it lets nobody through,
and saying so beats a login box that can never be satisfied.

The dashboard shows the history a benchmark exists to keep honest about, which
includes each task's hidden tests and the defect planted in it. Those are the
answer key, so they are a separate privilege from the scoreboard: a `viewer`
gets the runs, the scores and the task prose, and neither the files, nor the
task descriptor's mutation section, nor the download archive.

To put it on a network:

```bash
export AKBENCH_UI_USERS="analyst:$(python -c 'import secrets;print(secrets.token_urlsafe(18))'):viewer,judge:$(python -c 'import secrets;print(secrets.token_urlsafe(18))'):judge"
akbench ui --host 0.0.0.0 --port 8000
```

…behind TLS. HTTP Basic sends its password in the clear, and the command warns
when the bind address is not loopback. `/docs`, `/redoc` and `/openapi.json`
are off unless the app is built with `api_docs=True`.


## Layout

```text
src/akbench/
  cli/          # CLI layer (typer)
  config/       # Pydantic models + YAML/ENV loading
  core/         # errors, paths, time, logging
  descriptors/  # descriptor models, ENV allowlist, registry
  agents/       # adapter contract, agent registry, catalog, Codex adapter
  runtime/      # runtime manager contract, LLM Router adapter, execution modes
  evaluators/   # evaluator engine, pytest + command evaluators, isolation
  orchestration/  # run lifecycle state machine, the run orchestrator
  experiments/  # experiment descriptor, dimension registry, matrix strategies, planner
  storage/      # SQLAlchemy, models, Alembic migrations, migration runner
  datasets/     # task descriptors, dataset validation, repositories, workspaces
  bootstrap.py  # `akbench init` logic
  doctor.py     # environment diagnostics
tests/
  unit/         # paths, configuration, storage, doctor, descriptors, agents
  integration/  # CLI
  contract/     # shared adapter contract suite, fake agent, CLI stub
descriptors/    # component definitions (agents, plugins, models, ...)
datasets/       # task definitions, hidden tests and mutation patches
configs/        # configuration and experiment definitions
data/           # run directories, repository cache and database (git-ignored)
docs/           # integration and development documentation
spike/          # Phase 0 code (flow validation)
```

## Documentation

- `docs/ARCHITECTURE.md` — the modules, the plan-to-code mapping, and the place
  of the optional dashboard
- `docs/AGENT_INTEGRATION.md` — verified Codex CLI capabilities, including what
  its interface does **not** provide (cost, cancellation, session reset)
- `docs/ROUTER_INTEGRATION.md` — LLM Router: healthcheck, models, plugins,
  metrics and verification limits
- `docs/DESCRIPTOR_SYSTEM.md` — descriptor kinds, registries, ENV allowlist, dimension rules
- `docs/EXPERIMENT_DESCRIPTORS.md` — every block of an experiment file, field by field
- `docs/DIMENSION_DESCRIPTORS.md` — the nine dimension types, `source` routing, controllability
- `docs/EXPERIMENT_TYPES.md` — configuration / agent comparison / model comparison / knowledge replay
- `docs/FACTORIAL_DESIGN.md` — the five matrix strategies, baseline, deduplication, cost limits
- `docs/TASK_FORMAT.md` — `task.yaml` in full, mutations and `parts.json`, hidden tests
- `docs/CATEGORY_SYSTEM.md` — the nine categories, their difficulty gates, adding one
- `docs/RUNTIME_ADAPTERS.md` — the manager contract, the two lifecycles, `factor_env`, model evidence
- `docs/ISOLATION_AND_SECURITY.md` — what is isolated, how, and what AK-Bench does **not** guarantee
- `docs/DATASETS.md` — tasks, repositories, repeatable workspaces, mutation verification
- `docs/AGENT_ADAPTERS.md` — the adapter contract, agent registry, capability gating, contract tests
- `docs/RUNTIME_MANAGER.md` — execution modes, the runtime manager, the LLM Router adapter, the configuration triad
- `docs/EVALUATORS.md` — the evaluator engine, verdicts, hidden-test isolation, raw results
- `docs/RUN_ORCHESTRATOR.md` — the run lifecycle, isolation, retry policy and run records
- `docs/EXPERIMENTS.md` — experiment descriptors, validation, matrix strategies and planning
- `docs/PLUGINS.md` — the plugin adapter contract, verification and what a plugin can honestly report
- `docs/METRICS.md` — the metric catalog, per-run collection, aggregation and baseline deltas
- `docs/KNOWLEDGE_REPLAY.md` — the memory experiment: arms, scenarios, the readiness gate and isolation
- `docs/STORAGE.md` — the experiment history: tables, artifacts, the reproducibility manifest, verification
- `docs/REPORTING.md` — the static HTML reports: layout, the rules the numbers obey, cost and verification
- `docs/EXPORT.md` — the JSON, CSV and HTML export and the secret screening that precedes it
- `docs/REPRODUCIBILITY.md` — what "the same conditions" means here and where it is tested
- `docs/CLI.md` — every implemented command and the interface facts that go with it
- `docs/DEVELOPMENT.md` — development environment, tests, migrations
- `CHANGELOG.md` — release notes per version, with a short summary table at the top

## Plan conformance

The platform was built from `.plans/_partialy_done_to_verify/AK-Bench-implementation-plan.md`
(§1–30). An audit of that plan against this code, and the closed list of what
was missing, live next to it:

- `.plans/_partialy_done_to_verify/AK-Bench-audyt-planu.md` — the audit: phase by
  phase, section by section, with the evidence in the repository.
- `.plans/_partialy_done_to_verify/AK-Bench-plan-do-100-procent.md` — the plan of
  the gaps (phases A, C–K) and the state of each.

Two deviations are permanent and documented rather than fixed, and both are
stated where they apply: the Docker sandbox of plan §5/§14 is `deferred` —
host isolation is a worktree per run, a private `CODEX_HOME`, the agent's own
`sandbox_mode` and the copy-based evaluation sandbox
(`docs/ISOLATION_AND_SECURITY.md`) — and the plan's proposed directory sketch
is mapped to the real modules in `docs/ARCHITECTURE.md` instead of the code
being reshaped to match it.

## Conventions

Code, comments, docstrings, docs and commit messages are in English. Only the
implementation plan (`.plans/`) is written in Polish.

## License

MIT — see `LICENSE`.

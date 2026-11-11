# Architecture

This page maps the implementation onto the architecture the plan declares
(implementation plan, section 3), states the rules the code obeys (section 2),
and says where the optional dashboard sits in all of it.

## The shape of the system

```text
                         AK-BENCH
                             |
       +---------------------+----------------------+
       |                     |                      |
  Dataset Manager      Experiment Manager      Reporting
       |                     |                      |
       |               Experiment Planner           |
       |                     |                      |
       +--------------- Run Scheduler --------------+
                             |
                       Run Orchestrator
                             |
             +---------------+----------------+
             |                                |
       Agent Adapter                    Workspace Manager
             |                                |
      Tested Agent                         Git Worktree
             |
       Optional Runtime
             |
       +-----+-------------------------+
       |                               |
  Direct execution                 LLM Router
                                       |
                               Router Plugin System
                                       |
                         Knowledge / Routing / Optimization
             |
       Observability Adapters
             |
      Metrics / Events / Traces
             |
         Evaluator
             |
         Result Store
             |
       HTML / JSON / CSV
```

Every box in the diagram has a home in the code, and nothing in the code
belongs to more than one box:

| Module from the plan (§3.2) | Where it is |
|---|---|
| Dataset Manager | `src/akbench/datasets/` — `dataset.py` (loading, validation), `repository.py`, `workspace.py`, `verification.py` |
| Category Registry | `src/akbench/descriptors/category.py` + `descriptors/categories/` — categories are descriptors, not an engine enum (plan 8.1) |
| Repository Manager | `src/akbench/datasets/repository.py` — the bare cache and pinned commits |
| Mutation Engine | `src/akbench/datasets/workspace.py` (`prepare` applies the versioned patch) and `datasets/verification.py` (the proof that the defect exists) |
| Experiment Manager | `src/akbench/experiments/` — `descriptor.py`, `loader.py` |
| Experiment Planner | `src/akbench/experiments/planner.py`, `strategies.py`, `validation.py` |
| Agent Registry | `src/akbench/agents/registry.py`, `catalog.py` |
| Agent Adapter | `src/akbench/agents/contract.py` (the protocol), `codex.py`, `fake.py`, `http.py` |
| Runtime Manager | `src/akbench/runtime/contract.py`, `llm_router.py`, `registry.py` |
| Plugin Registry | `src/akbench/plugins/registry.py`, `adapter.py`, `descriptors/plugin.py` |
| Workspace Manager | `src/akbench/datasets/workspace.py` — a git worktree per run over a shared bare cache |
| Run Orchestrator | `src/akbench/orchestration/orchestrator.py`, `lifecycle.py`, `cancellation.py` |
| Evaluator Engine | `src/akbench/evaluators/` — `engine.py`, `registry.py`, the five evaluators, `isolation.py` |
| Knowledge Experiment Manager | `src/akbench/knowledge/` — `modes.py`, `planning.py`, `readiness.py`, `fingerprint.py`, `isolation.py` |
| Observability | `src/akbench/metrics/` (`collect.py`, `aggregate.py`, `catalog.py`) and the plugin adapter's normalization |
| Result Store | `src/akbench/storage/` — SQLAlchemy models, Alembic migrations, `history.py`, `manifest.py` |
| Reporting Engine | `src/akbench/reporting/` — `data.py`, `render.py` (static HTML) |
| Export Manager | `src/akbench/export/` — `exporter.py`, `redact.py`, `filters.py` |

The plan's proposed directory sketch (§5.1) does not match the real one, and
the differences are deliberate:

- No `categories/`, `repositories/`, `mutations/`, `discovery/`, `sandbox/`,
  `runner/` or `observability/` packages: their responsibilities are the
  modules above. The categories live in the descriptor registry, the
  repository and mutation handling in `datasets/`, the "runner" is the
  orchestrator, and observability is the metrics plus plugin layers.
- `descriptors/` holds both the models (`src/akbench/descriptors/`) and the
  component definitions at the project root (`descriptors/<kind>/`), and the
  plan's `dataset/` is `datasets/` here.
- `data/` and `reports/` are created on demand by `akbench init`; they are
  local state, not code.
- The plan names Docker in the stack; it is not implemented (phase B is
  `deferred`), so there is no `sandbox/` package and the environment
  descriptors mark the container as unavailable. See
  `docs/ISOLATION_AND_SECURITY.md`.

## The rules the code obeys (§2)

1. **The agent is a replaceable component.** The engine talks to the adapter
   contract (`agents/contract.py`), never to an agent. The string "codex"
   appears in the engine, the planner, the scheduler and the evaluators
   nowhere; it lives in `agents/codex.py` and its descriptor.
2. **Components and descriptors are versioned and digest-pinned.** A plan
   records the digests of every descriptor it used, so editing a descriptor
   cannot reinterpret a historical result (plan 9, 10).
3. **Configuration is recorded in three states.** `requested`, `effective`
   and `observed` are stored separately with a `verification_status`; a
   configuration is never active without verification (plan 7, 13).
4. **Unknown capabilities are `unsupported` or `unverified`, never faked.**
   The same vocabulary runs through agents, runtimes, plugins, metrics and
   evaluators (plan rule 9, 25).
5. **Infrastructure failures are not agent failures.** `FailureClass` and the
   run states keep the two apart, so a network blip is never scored against
   the agent (plan rule 11).
6. **Every run is isolated and identified.** A worktree per run, a fresh agent
   session, hidden tests outside the workspace, and a reproducibility
   manifest that states what the run was (plan 14).
7. **Results are reproducible at the level of conditions.** Identical task,
   agent, runtime, configuration and descriptors — not identical model
   answers (plan 10, 24).

## The interfaces, and where the dashboard fits

The primary interfaces are the CLI and the static HTML reports. The CLI is
the whole control surface (`docs/CLI.md`); `akbench report all` renders the
recorded history into a self-contained HTML tree under `reports/`
(`docs/REPORTING.md`), and it is the view that must always exist.

`bench_ui/` is an optional add-on, not a dependency of the benchmark:

- `akbench ui` starts it on request; the FastAPI app serves the same recorded
  history plus a live view, bound to loopback by default with its own
  authentication (README, "Serving the dashboard").
- The benchmark does not import it. It is the other direction that is guarded:
  `tests/unit/test_bench_ui_import.py` fails if importing `bench_ui` or
  building the app reaches for a database, because the dashboard must start
  without one and the benchmark must not need it at all.
- Absent the dashboard, nothing is lost: every number it shows is in the
  history, and the history renders without it.

## What this page is not

It is not an API reference (the contracts live in the modules it names) and
not a design history. It states what the system is now, where each
responsibility of the plan sits, and the two facts a newcomer most often
misses: the dashboard is optional, and the container isolation is not there.

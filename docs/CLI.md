# CLI

Every command from the plan's CLI sketch is implemented. Global options:
`--config/-c`, `--project-root`, `--verbose/-v`, `--quiet/-q`, `--version`.
Nearly every command accepts `--json`; where a command can fail, a non-zero
exit code is part of the interface.

## Interface facts

| Command | Notes |
|---|---|
| `akbench version` | AK-Bench and key dependency versions |
| `akbench init` | create directories, configuration and schema |
| `akbench doctor [--strict]` | environment diagnostics; exit 1 on failures |
| `akbench config show [--all]` / `config validate` | effective configuration, paths, database URL |
| `akbench descriptor list/validate/show` | descriptor registry |
| `akbench category list` | task categories and whether they are enabled |
| `akbench dataset list/validate/show/prepare` | tasks, repositories, repeatable workspaces |
| `akbench agent list/inspect/run` | registered agents and one agent run |
| `akbench runtime list/health/models/config/state` | runtimes and their configuration triad |
| `akbench runtime status [REF]` | one runtime in full (as `state`), or the whole registry |
| `akbench runtime start/stop REF` | managed instance outside a run; `external` refuses |
| `akbench runtime verify REF [--expect k=v]` | health, configuration triad, expected-vs-effective |
| `akbench evaluate task` | judge a produced workspace |
| `akbench evaluator list` | the evaluators this installation implements |
| `akbench run single TASK --agent A [--store]` | one orchestrated run |
| `akbench experiment list/validate/plan` | validate and expand an experiment |
| `akbench experiment run FILE [--store] [--only N] [--concurrency N]` | execute the matrix |
| `akbench experiment show UID` | one recorded experiment: plan, variants, runs, metrics |
| `akbench experiment resume UID` | run the cells the history has no verdict for |
| `akbench experiment cancel UID` | ask a running matrix to stop |
| `akbench plugin list/status/verify` | plugin descriptors and their observed state |
| `akbench metrics catalog/run` | the metric catalog and the metrics of recorded runs |
| `akbench knowledge plan/readiness` | the memory plan and the readiness gate |
| `akbench history experiments/runs/show/metrics/verify` | read the recorded history back |
| `akbench report all/experiment/task` | write the static HTML reports |
| `akbench export experiment UID [--no-prompts] [--no-diffs] [--no-traces]` | write one experiment out, screened; the switches leave prompts, the produced change or the traces out, and the export says what it left out |
| `akbench export experiment UID --include-artifacts` | also copy the run's artifacts, the filters deciding what may be copied |
| `akbench ui [--host H] [--port P]` | start the FastAPI dashboard; optional, the benchmark never needs it (README, "Serving the dashboard") |
| `akbench migrate list` / `migrate sqlite FILE…` | list the imported namespaces, or import SQLite histories into the shared PostgreSQL database, one namespace each |

## Conventions that are part of the interface

- `--json` prints a machine-readable document on stdout and nothing else that
  is not part of it; human output goes through the console renderer.
- A command that cannot do its job exits non-zero. A command that can do part
  of it says which part it could not (e.g. `history verify` lists what does not
  match, then exits 1).
- Nothing is stubbed. An unimplemented capability is absent, not simulated:
  `doctor` and the commands report what is actually present.
- `--store` on the run and experiment commands records the run, its manifest
  and its artifacts in the history; without it, nothing is written there.

## Plan (§22) versus implementation

| Command from the plan | Here | Note |
|---|---|---|
| `init`, `doctor` | same | |
| `agent list`, `agent inspect codex` | same | |
| `descriptor list`, `descriptor validate` | same | |
| `dataset list`, `dataset validate`, `category list` | same | |
| `runtime status` | `runtime status` (and `state`) | `status` without an argument lists every runtime |
| `runtime start` | `runtime start` / `runtime stop` | managed only; an instance outlives the command, `stop` takes it down |
| `runtime verify` | `runtime verify` | health + configuration triad + `--expect` diff |
| `experiment validate/plan/run` | same | `run` takes `--concurrency`, `--only`, `--store` |
| `experiment list` | same | the definitions this project ships |
| `experiment show exp-0001` | same | read from the history, including the file as it was run |
| `experiment resume exp-0001` | same | fills the matrix cells without a verdict |
| `experiment cancel exp-0001` | same | see below — there is no daemon to signal |
| `report --experiment/--all` | `report experiment UID` / `report all` | subcommands rather than flags |
| `export --experiment UID --format json` | `export experiment UID [--format json]` | as above |
| (not in the sketch) | `migrate list` / `migrate sqlite FILE…` | added later: the shared mode needs a way to bring the local histories over, one namespace each |
| (not in the sketch) | `ui` | added later: the dashboard is an optional add-on, and the plan's own rule is that the CLI plus static HTML are the primary interfaces |

## How cancel works without a daemon

The CLI is one-shot: `akbench experiment run` is the scheduler and lives only
while it runs. Cancellation therefore has two honest shapes.

- `Ctrl+C` in the running process asks the run in flight to stop through the
  same token a cancel carries: the agent is interrupted, its run is recorded
  `cancelled` with its artifacts, and no further cell starts. The second press
  leaves the way it always did. `run single` and `agent run` behave the same.
- `akbench experiment cancel UID` writes a marker under
  `data/cancellations/`, which a running matrix of that uid watches; it stops
  within a second. A matrix that starts later clears the marker first, so a
  request that arrived after the fact cannot cancel the next experiment.

Resume reads the plan back from the experiment file recorded with it and runs
the cells the history has no verdict for. A cell is the triple (task, variant,
repetition); every terminal state counts except `cancelled`, which is an
operator asking rather than a result — so an interrupted cell is exactly what
a resume re-runs, and resuming a finished experiment does nothing, twice.

Concurrency comes from `execution_policy.concurrency` (or `--concurrency`):
runs go through a thread pool — an agent is a subprocess — and results are
collected in plan order, not in the order the runs finished. The plan warns
about it, because N runs at once share the machine and the router, and
per-run timings then measure a loaded system.

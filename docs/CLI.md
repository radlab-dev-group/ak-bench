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
| `akbench evaluate task` | judge a produced workspace |
| `akbench run single TASK --agent A [--store]` | one orchestrated run |
| `akbench experiment list/validate/plan` | validate and expand an experiment |
| `akbench experiment run FILE [--store] [--only N]` | execute the matrix |
| `akbench plugin list/status/verify` | plugin descriptors and their observed state |
| `akbench metrics catalog/run` | the metric catalog and the metrics of recorded runs |
| `akbench knowledge plan/readiness` | the memory plan and the readiness gate |
| `akbench history experiments/runs/show/metrics/verify` | read the recorded history back |
| `akbench report all/experiment/task` | write the static HTML reports |
| `akbench export experiment UID` | write one experiment out, screened |

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

## Intentionally absent

`experiment resume` and `experiment cancel` need a scheduler with a queue of
runs in flight; there is none yet, so the commands are absent rather than
accepting arguments and doing nothing.

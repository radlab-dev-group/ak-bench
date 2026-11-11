# Experiment descriptors

An experiment is a versioned YAML file that states what will be measured: the
agent, the execution mode and its runtime, the task selection, the factors and
their strategy, the policy, the isolation, the evaluators, the metrics and the
limits. This page is the field reference for `ExperimentBody`
(`src/akbench/experiments/descriptor.py`), the validation the planner runs over
it (plan section 12.1) and the limits that bound what it costs.
`docs/EXPERIMENTS.md` explains the workflow and the shipped files; this page is
the schema.

## The document

```yaml
schema_version: "1.0"
id: knowledge-on-off
version: "1.0.0"
title: Knowledge plugin on/off
description: >-
  What the experiment measures, in the words a reader of a report needs.

experiment:
  type: configuration
  agent:
    id: codex
    version: "1.0.0"
    config:
      sandbox_mode: workspace-write
      model: qwen/Qwen3.8-27B
  execution:
    mode: router
    runtime:
      id: llm-router-ak-bench
      lifecycle: managed
  dataset:
    filters:
      categories: [bug_fix]
      task_ids: [wordcount-001, slugify-001]
  factors:
    strategy: custom_matrix
    dimensions:
      - id: knowledge_enabled
    baseline:
      knowledge_enabled: false
    combinations:
      - knowledge_enabled: false
      - knowledge_enabled: true
        runtime_env:
          LLM_ROUTER_UTILS_PLUGINS_PIPELINE: agentic_knowledge
  execution_policy:
    repetitions: 3
    concurrency: 1
    timeout_seconds: 900
    retry_infrastructure_errors: 1
  isolation:
    workspace_per_run: true
    fresh_agent_session: true
    clean_agent_context: true
  evaluation:
    evaluators: [pytest_evaluator]
  metrics:
    - task_success_rate
    - hidden_test_pass_rate
  limits:
    max_runs: 64
```

The header is the shared descriptor header (`schema_version`, `id`, `version`,
`title`, `description`); an experiment is registered like any other component,
so its digest is pinned in every plan and run built from it. Files live in
`configs/experiments/` — they reference the registries rather than being part
of them.

Every model in the file is strict (`extra="forbid"`): a key nobody reads is a
mistake that must be reported, not a setting silently ignored while the
experiment runs something other than what its author meant.

## `experiment.type`

One of `configuration`, `agent_comparison`, `model_comparison`,
`knowledge_replay` (plan 12, 25). What each means, and what the validator
insists on, is in `docs/EXPERIMENT_TYPES.md`. Configuration and learning
experiments are kept apart on purpose: mixing them makes a memory effect
indistinguishable from a configuration change (plan rule 16).

## `experiment.agent`

The agent under test: `id` (required), optional `version`, and `config`, the
agent-specific parameters every arm shares. Each key must be a parameter the
agent descriptor declares and declares controllable, and its value must be in
the descriptor's allowed set (`agent_parameter_unknown`,
`agent_parameter_uncontrollable`, `agent_parameter_value`). A parameter a
factor also varies is a contradiction (`factor_config_conflict`) — the factor
owns it.

## `experiment.execution`

`mode` is one of `direct`, `runtime`, `router` (default `direct`) and
`runtime` is the runtime selection: `id`, optional `lifecycle`, and `env`.

- A runtime in `direct` mode is refused by the model itself.
- `runtime.env` is the launch environment the experiment declares for the
  instance its runs start, applied to every arm; it needs a managed runtime
  with a launch block (`runtime_environment_needs_managed`). The per-arm form
  is a combination's `runtime_env` under `factors`
  (`docs/RUNTIME_ADAPTERS.md`).

## `experiment.dataset`

`id`/`version` of a dataset (the loader works from the project's `datasets/`
directory), optional `path`, and `filters` — `categories`, `difficulties`,
`task_ids`, each a list narrowing the selection. A selection that matches
nothing is refused (`dataset_selection_empty`), because zero tasks produce zero
evidence, and a `path` that does not exist is `dataset_path_missing`.

## `experiment.factors`

The matrix declaration (plan 12.2; strategies in `docs/FACTORIAL_DESIGN.md`):

| Field | Meaning |
|---|---|
| `strategy` | `full_factorial` (default), `selected_factors`, `one_factor_at_a_time`, `pairwise`, `custom_matrix` |
| `dimensions` | the factors: each `{id, values?}` where `values` narrows the dimension's declared value space |
| `selected` | the factors that vary under `selected_factors` |
| `baseline` | the reference configuration, as factor values |
| `combinations` | the explicit rows of `custom_matrix`; a row may carry the reserved key `runtime_env` |

Two ids are reserved and refused as factors: `repetition` (repetitions are
governed by `execution_policy.repetitions`) and `runtime_env` (the environment
of a combination is not a factor value). Duplicate dimension ids are refused.
A factor whose dimension is not controllable, or which names a value the
dimension does not declare, cannot be resolved (`factor_unusable`) — an
uncontrollable dimension may be observed, never varied (plan 11).

## `experiment.execution_policy`

| Field | Default | Bound |
|---|---|---|
| `repetitions` | 1 | 1…1000 |
| `concurrency` | 1 | 1…64; above 1 the plan warns (`concurrency_above_one`), because N runs at once share the machine and the router and per-run timings then measure a loaded system |
| `timeout_seconds` | none | unset warns (`timeout_undeclared`): a hung agent with no deadline leaves the plan's cost unbounded |
| `evaluation_timeout_seconds` | none | the evaluator's own budget |
| `retry_infrastructure_errors` | 0 | 0…10; infrastructure retries are explicit and recorded (plan 15) |
| `retry_agent_failures` | 0 | **must stay 0** — retrying an agent failure measures the retry, not the agent |

## `experiment.isolation`

Plan section 14, and two of its four fields are not negotiable:

- `workspace_per_run` — cannot be `false`: two runs in one workspace
  contaminate each other.
- `fresh_agent_session` / `clean_agent_context` — `clean_agent_context`
  requires `fresh_agent_session`, because a reused session carries the previous
  run's context.
- `cleanup_workspace` — default `false`: workspaces stay until the operator
  removes them, because they are evidence.

## `experiment.environment`

An optional `{id, version}` reference to an Environment Descriptor (plan 9):
`local-host` today, and `docker-python312` refused at planning
(`environment_sandbox_unavailable`) because the container isolation is not
implemented. The identity, the sandbox kind and the descriptor digest go into
the run record and the manifest, so a run states where it happened.

## `experiment.evaluation` and `experiment.metrics`

`evaluation.evaluators` names registered evaluator ids, each of which must also
be implemented here (`evaluator_undeclared`, `evaluator_not_implemented`).
`evaluation.baseline` is `base_state` or `none`. `metrics` lists registered
metric ids (`metric_undeclared`); a metric that cannot be computed in this
installation is a warning (`metric_unavailable`) and stays reported as
unavailable rather than as a zero (`docs/METRICS.md`).

## `experiment.limits`, `experiment.reporting`

`limits` bounds the plan's cost: `max_runs`, `max_variants`, `max_tasks`, each
`>= 1`. Exceeding one is an error, not a warning (`limit_runs`,
`limit_variants`, `limit_tasks`), because the point of a limit is that a
mistaken matrix must not start. `reporting` selects `generate_html`,
`generate_json` (default true) and `generate_csv`.

## `experiment.knowledge` and `experiment.required_capabilities`

`knowledge` exists only for `type: knowledge_replay` (and that type requires
it): the learning tasks, the replay readiness gate, the mandatory fresh control
and the scenarios (`docs/KNOWLEDGE_REPLAY.md`). `required_capabilities` lists
capabilities every arm must provide; an arm that cannot provide one is refused
(`capability_unavailable`) rather than run and recorded with holes.

## What validation refuses

The planner runs the checks of plan 12.1 before anything starts and lists them
by stable code. The full table, the meaning of a warning versus an error, and
the commands to run are in `docs/EXPERIMENTS.md`. Three refusals are worth
restating because they are the ones people argue with:

- a configuration that cannot be pinned to a run is not an experimental
  control — a plugin factor against a runtime that cannot own it is refused
  (`per_run_plugin_control_unsupported`), not assumed applied;
- a declared launch environment with no process to apply it to is refused
  (`runtime_environment_needs_managed`);
- a baseline that does not appear in the generated matrix is refused
  (`baseline_not_in_matrix`): a comparison without a reference answers nothing.

A variant is then identified by a `variant_id` derived from its requested
configuration — factor values, agent parameters, environment requests and the
launch environment — hashed with the experiment's source digest, and pinned to
the digests of every descriptor it used (plan 12.3, 9).

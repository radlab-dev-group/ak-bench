# Experiments and planning

An experiment is a versioned YAML definition of what will be measured
(plan sections 11 and 12). It names the agent, the optional runtime, the
dataset selection, the factors, the matrix strategy, the repetitions, the
isolation policy, the evaluators and the metrics. The file lives in
`configs/experiments/` because it is the researcher's input, not an installed
component: it *references* the registries instead of being part of them.

## Plan before run

Planning is a separate step from execution (plan 12.2), and it never touches a
workspace, an agent or the network:

```bash
akbench experiment list
akbench experiment validate                 # every file in configs/experiments
akbench experiment validate FILE [FILE...]  # a subset
akbench experiment plan FILE --variants --json
```

The plan reports the four numbers that decide what an experiment costs —
tasks, variants, repetitions and runs — and a cost bound derived from the
declared timeout. A descriptor that is not runnable is rejected at validation,
so the rejection happens before an agent is started, with the reasons listed
by a stable code.

## Validation

The checks of plan 12.1, each with the code it reports:

| Check | Code |
|---|---|
| the dataset selection is not empty | `dataset_selection_empty` |
| the agent is described and its adapter is implemented | `agent_unknown`, `agent_parameter_unknown`, `agent_parameter_uncontrollable`, `agent_parameter_value` |
| required capabilities are usable (verified or partial) | `capability_unavailable` |
| the runtime exists, supports the mode and the lifecycle | `runtime_unknown`, `runtime_mode_unsupported`, `runtime_lifecycle_unsupported` |
| plugin factors can be owned by this experiment | `plugin_factor_without_runtime`, `per_run_plugin_control_unsupported` |
| factors are resolvable dimensions with controllable, declared values | `factor_unusable` |
| evaluators are described and implemented | `evaluator_undeclared`, `evaluator_not_implemented` |
| metrics are described; uncomputable ones are flagged | `metric_undeclared`, `metric_unavailable` (warning) |
| the plan fits the declared limits | `limit_runs`, `limit_variants`, `limit_tasks` |
| the declaration is self-consistent | `factor_config_conflict`, `comparison_without_factor`, `baseline_value_invalid`, `baseline_not_in_matrix`, `strategy_failed` |

Two refusals are structural, not advisory. A factor whose value the interface
cannot set is not a factor: uncontrollable dimensions may be observed, never
varied (plan 11), and a plugin factor against a runtime that cannot configure
plugins per run is rejected rather than assumed applied (plan 13, rule 14).
A managed runtime is the exception, and the plan says so with a warning: the
value is applied at start, but verification still needs the plugin's own
signal.

## Strategies

| Strategy | Meaning |
|---|---|
| `full_factorial` | the cross product of every factor |
| `selected_factors` | only `factors.selected` varies; the rest is pinned to the baseline |
| `one_factor_at_a_time` | the baseline plus one change of one factor value at a time |
| `pairwise` | a greedy covering array: every pair of values appears in some variant |
| `custom_matrix` | exactly the declared `combinations`, in that order |

Every strategy is deterministic, and every variant carries a stable id derived
from the requested configuration, a hash of that configuration, the requested
agent parameters and the environment requests, and a baseline flag. The plan
pins the digests of every descriptor it depends on (plan 9), so editing a
descriptor later cannot reinterpret the plan.

## The shipped examples

| File | What it shows |
|---|---|
| `wordcount-direct-sanity.yaml` | the reference case: one task, one agent, no factors |
| `knowledge-on-off.yaml` | a plugin factor against a managed router (plan 25, B) |
| `model-comparison.yaml` | one-factor-at-a-time over models (plan 25, D) |
| `full-matrix.yaml` | knowledge × model, a full factorial (plan 25, E) |

The plan's example E adds Auto Codex as a third axis; it is deliberately left
out of `full-matrix.yaml` because the router in this installation refuses
per-run control of the routing alias. A smaller matrix whose cells are all
real is preferred over a larger one whose cells are assumed.

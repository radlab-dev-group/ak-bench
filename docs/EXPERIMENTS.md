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
| the declared environment exists and its sandbox is available | `environment_unknown`, `environment_sandbox_unavailable` |
| concurrency above one is visible before the run | `concurrency_above_one` (warning) |
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

## Where the runs happen

An experiment may name the environment its runs execute in:

```yaml
experiment:
  environment:
    id: local-host      # descriptors/environments/local-host.yaml
```

The reference is checked like any other component reference (it has to exist,
and its digest is pinned in the plan's snapshots), and the run records the
environment identity, its sandbox kind and the descriptor's digest — in the run
record and in the reproducibility manifest, next to `sandbox_image`.

Two environments ship today. `local-host` is the honest statement of where
AK-Bench runs: the operator's machine, network reachable, the only isolation
being the per-run workspace. `docker-python312` is plan 14's container,
declared before it is enforced: selecting it is refused with
`environment_sandbox_unavailable`, because a run that asked for a container and
quietly got the host would record an isolation it never had.

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

### The launch environment of a combination

A `custom_matrix` combination may carry a reserved key `runtime_env`, a
mapping of environment variables to scalar values. It is the environment the
run's **managed** runtime instance is started with: the planner strips the key
from the factor values, the variant's identity hashes it, the orchestrator
hands it to the runtime adapter, and the adapter applies it last, so it wins
over the descriptor's static environment and over the ambient shell.

```yaml
  factors:
    strategy: custom_matrix
    dimensions:
      - id: model
      - id: knowledge_enabled
    combinations:
      - model: qwen/Qwen3.8-27B
        knowledge_enabled: false
        runtime_env:
          LLM_ROUTER_UTILS_PLUGINS_PIPELINE: agentic_routing_codex
      - model: auto_codex
        knowledge_enabled: true
        runtime_env:
          LLM_ROUTER_UTILS_PLUGINS_PIPELINE: agentic_routing_codex,agentic_knowledge
```

This exists because some configuration is fixed when a process starts: the
plugin pipeline of a router is read at launch, so an arm that wants a plugin
has to name it in its combination, and the runtime descriptor ships no
pipeline of its own (a pipeline there would load its plugins in **every** run
of that runtime, including the arms that measure the router without them).
Declaring `runtime_env` against a runtime that is not started by the run is a
plan error (`runtime_environment_needs_managed`): an environment sent nowhere
is not a configuration. The environment the run declared is recorded in the
run record as `runtime_environment` and named in the plan and run output.

## The shipped examples

| File | What it shows |
|---|---|
| `wordcount-direct-sanity.yaml` | the reference case: one task, one agent, no factors |
| `knowledge-on-off.yaml` | a plugin factor on the self-start instance (plan 25, B) |
| `model-comparison.yaml` | one-factor-at-a-time over models, external instance (plan 25, D) |
| `full-matrix.yaml` | knowledge × model, a full factorial on the self-start instance (plan 25, E) |
| `router-config-comparison.yaml` | the operator's four-arm comparison, every arm started on its own instance |
| `llm-router-external-fast.yaml` | the cheap shared-instance comparison: the model arms only |
| `llm-router-selfhost-fast.yaml` | the same shape on an instance the run owns, with the knowledge plugin |
| `knowledge-replay.yaml` | a memory experiment; the managed instance gives it its own namespace |
| `arena-roadmap-knowledge.yaml` | the fifty arena and roadmap tasks, one arm: the routing alias over the 27B base model, knowledge on |

The split between the two runtimes is a rule, not a choice per file: an
experiment varies a *plugin* configuration only where the run owns the
process — that is `llm-router-ak-bench`, `lifecycle: managed`, and each arm
names the plugin pipeline its instance starts with. An experiment that only
sends requests — model values, plain runs — names the shared instance,
`llm-router-external`, `lifecycle: external`, and claims no control it does
not have. The shared descriptor declares `external` only; a plan that asked it
for `managed` would be refused, because a shared instance AK-Bench does not
start is not a managed one.

The plan's example E adds Auto Codex as a third axis; it is deliberately left
out of `full-matrix.yaml` because the router in this installation refuses
per-run control of the routing alias. A smaller matrix whose cells are all
real is preferred over a larger one whose cells are assumed.

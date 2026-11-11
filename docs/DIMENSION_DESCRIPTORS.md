# Dimension descriptors

A dimension is a factor of an experiment: one parameter with a declared type,
a declared value space, and a declared statement of how it is set and how it
can be verified (implementation plan, section 11). This page is the reference
for the descriptor (`src/akbench/descriptors/dimension.py`), the nine types,
the meaning of `source`, controllability, and how a value actually reaches a
process.

## The descriptor

A Dimension Descriptor lives in `descriptors/dimensions/`:

```yaml
schema_version: "1.0"
id: knowledge_enabled
version: "1.0.0"
title: Knowledge plugin enabled
description: Turns the agentic knowledge layer on or off for a run.

dimension:
  type: plugin_configuration
  source: plugin.agentic_knowledge.env
  values: [false, true]
  default: true
  controllable: true
  observed: true
  configure_via: env LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED on the router process
  verify_via: >-
    requires effective_router_config or plugin_runtime_events. Neither is
    reachable on the external instance (configuration reads are refused and no
    per-plugin counter is exported), so a run against it stays unverified and
    needs a managed router to become verified.
  depends_on:
    - plugin agentic_knowledge present in LLM_ROUTER_UTILS_PLUGINS_PIPELINE
```

The body (`DimensionBody`) is strict. Its fields:

| Field | Meaning |
|---|---|
| `type` | one of the nine types below |
| `source` | where the value comes from and where it goes; the planner routes it by this string |
| `values` | the declared value space; required for a controllable categorical, string or reference type |
| `minimum` / `maximum` | the bounds of an `integer` or `float` dimension |
| `default` | the value an experiment gets when it does not vary this dimension |
| `controllable` | whether AK-Bench may set it — the only gate on becoming a factor |
| `observed` | whether it should be recorded (default `true`) |
| `configure_via` | how it is configured, stated in the words of the interface |
| `verify_via` | what would count as confirming it, and what the current limit is |
| `depends_on` | preconditions of the value having any effect |
| `notes` | free text |

Model-level rules, enforced by the descriptor itself: a boolean may list only
`[true, false]`; an integer or float may declare bounds, and `minimum` must not
exceed `maximum`; a controllable categorical, string or reference dimension
must declare `values`; `values` may never be an empty list.

## The nine types

The plan lists nine; `DimensionType` implements all nine:

| Type | Value space | Notes |
|---|---|---|
| `boolean` | `[false, true]`, implicit | the natural shape of a toggle |
| `categorical` | declared `values` | anything with a named, finite set of options |
| `integer` | bounds (`minimum`/`maximum`) or declared values | range-checked per value |
| `float` | bounds or declared values | range-checked per value |
| `string` | declared `values` when it generates variants | a free string is not a value space |
| `agent_reference` | Agent Descriptor ids | selects the adapter per variant |
| `model_reference` | model ids | requested or observed, depending on `source` |
| `plugin_configuration` | declared values | a plugin's own configuration, applied through the runtime |
| `runtime_configuration` | declared values | a runtime-level setting |

The last four are the "reference" and "range" families the code treats
specially: reference types are resolved through the registries (an arm must be
a component that exists), range types are checked against bounds rather than
against an enumerated list.

## `source`: where a value goes

`source` is the routing rule. The planner reads it and only it:

| `source` | Destination | Controllable in practice |
|---|---|---|
| `agent.configuration.<param>` | an agent parameter — `model` becomes `codex -m/--model` | yes, if the agent declares `<param>` controllable |
| `experiment.agent.id` | which agent/adapter runs (`agent` dimension) | yes |
| `plugin.<plugin-id>.env` | the runtime process environment, through the runtime's `factor_env` map | yes, against a managed instance only |
| `runtime.response.<field>` | observation only — the value comes back from the runtime | no |
| `experiment.execution_policy.repetitions` | the repetition axis, declared by the policy | no |

Two consequences are load-bearing:

- **A plugin factor is only a control when a process can be started with it.**
  The value travels `factor_env` → the environment of the instance the run
  launches (`docs/RUNTIME_ADAPTERS.md`), which means a managed runtime; against
  a shared instance the plan is refused rather than the value quietly ignored
  (`docs/EXPERIMENTS.md`).
- **An observed dimension never generates variants.** `runtime.response.model`
  (`routed_model`) is the model that actually served a request: it is recorded
  and compared, and `usable_as_factor` is `false` for it, so the planner
  rejects it as a factor even when an experiment asks. Conflating it with the
  requested model would turn a request into a measurement.

## Controllability

`controllable` is a claim about an interface, not about a wish. A factor is a
dimension resolved through `DimensionRegistry.factor`
(`src/akbench/experiments/dimensions.py`), which raises unless:

1. the dimension is controllable — "uncontrollable dimensions may be observed,
   never varied (plan 11)";
2. there is a value space to draw from: the dimension's `values`, or — for a
   range type, which has no enumerated space — the values the experiment factor
   itself lists. Bounds alone are not a value space, and the error says so
   ("list the values to try in the experiment factor");
3. every requested value is declared (or within bounds), with no duplicates.

The experiment may narrow a dimension's values (`factors.dimensions[].values`)
but never widen it: a value the dimension does not list is rejected even when
it looks plausible, because the dimension carries the *verified* value space —
for instance the model ids the router under test really serves, plus the
routing alias that resolves although `/v1/models` omits it. A factor's own
narrowing is then decisive for baselines and combinations: a value outside it
is not part of this experiment even though the dimension declares it.

## The shipped dimensions

| Id | Type | `source` | Factor? |
|---|---|---|---|
| `agent` | `agent_reference` | `experiment.agent.id` | yes — the arms of an agent comparison |
| `model` | `model_reference` | `agent.configuration.model` | yes — requested model, passed to the agent |
| `routed_model` | `model_reference` | `runtime.response.model` | no — observed only |
| `repetition` | `integer` | `experiment.execution_policy.repetitions` | no — the policy owns repetitions |
| `knowledge_enabled` | `plugin_configuration` | `plugin.agentic_knowledge.env` | yes |
| `knowledge_read_enabled` | `plugin_configuration` | `plugin.agentic_knowledge.env` | yes |
| `knowledge_write_enabled` | `plugin_configuration` | `plugin.agentic_knowledge.env` | yes |
| `knowledge_escalation_enabled` | `plugin_configuration` | `plugin.agentic_knowledge.env` | yes |
| `routing_heuristic_enabled` | `plugin_configuration` | `plugin.agentic_routing_codex.env` | yes |
| `routing_semantic_enabled` | `plugin_configuration` | `plugin.agentic_routing_codex.env` | yes |

`repetition` is declared so a report can name the axis, and the planner
refuses it as a factor; the experiment declares repetitions in
`execution_policy` instead. The plugin dimensions name in `verify_via` what
evidence would confirm their effect and what the limit is today — which is the
reason a plugin arm is recorded as applied-but-unverified on a shared router
and applied-by-construction on a managed one.

## Adding a dimension

A new factor is one file, and then the plumbing it names:

```yaml
# descriptors/dimensions/knowledge_top_k.yaml
schema_version: "1.0"
id: knowledge_top_k
version: "1.0.0"
title: Knowledge retrieval top-k
description: How many knowledge entries the plugin retrieves per request.

dimension:
  type: integer
  source: plugin.agentic_knowledge.env
  minimum: 1
  maximum: 10
  default: 3
  controllable: true
  observed: true
  configure_via: env LLM_ROUTER_KNOWLEDGE_AGENTIC_TOP_K
  verify_via: the plugin's own configuration read, where one exists
```

A range dimension declares bounds and no list, so an experiment that uses it
names the values to try (`values: [1, 3, 5]` under the factor); the bounds are
what those values are checked against.

For a plugin dimension the runtime descriptor must then carry the matching
`factor_env` line (`knowledge_top_k: LLM_ROUTER_KNOWLEDGE_AGENTIC_TOP_K`), and
for an agent parameter the agent descriptor must declare the parameter
controllable. Without those, the dimension is describable but not usable —
which is the point: the descriptor states the intent, the two other files state
that an interface really carries it, and the planner is where a missing link
becomes an error rather than an experiment that runs and changes nothing.

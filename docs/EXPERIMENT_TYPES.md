# Experiment types

`experiment.type` says what an experiment varies, and the validator treats it
as a claim about the file rather than as a label (implementation plan, sections
12 and 25). Four types are implemented; this page states what each is for, what
it requires, and what the planner refuses. The commands and the full validation
table are in `docs/EXPERIMENTS.md`; the field reference is in
`docs/EXPERIMENT_DESCRIPTORS.md`.

| Type | What varies | Shipped example |
|---|---|---|
| `configuration` | anything but the agent: a plugin toggle, a model, a runtime setting | `knowledge-on-off.yaml`, `full-matrix-12.yaml`, `wordcount-direct-sanity.yaml` |
| `agent_comparison` | which agent runs, and nothing else | `agent-comparison.yaml` |
| `model_comparison` | the requested model, agent and configuration held still | `model-comparison.yaml` |
| `knowledge_replay` | whether the agent has the knowledge it wrote earlier | `knowledge-replay.yaml`, `knowledge-replay-memory-suite.yaml` |

## `configuration`

The default and the general case: an experiment that measures the effect of a
configuration on the same agent. The factors are the interesting part, and the
rules that bite are the general ones — a factor must be a controllable
dimension with declared values, a plugin factor needs a runtime that can own
it, a declared launch environment needs a managed instance.

A configuration experiment with no baseline declared gets a warning
(`baseline_undeclared`): differences between variants then have no reference
point in the report. A baseline that is declared but does not appear among the
generated variants is an error (`baseline_not_in_matrix`).

## `agent_comparison`

The same tasks, the same evaluator, the same execution mode — and different
agents (`docs/AGENT_ADAPTERS.md`). Two things make the comparison honest, and
the planner enforces both.

**The `agent` factor must vary.** A `type: agent_comparison` whose matrix does
not contain the `agent` dimension is refused (`comparison_without_factor`),
and one whose matrix holds only the primary agent is warned about
(`agent_comparison_single_arm`): a comparison with one arm is a run.

**Every arm must be a described agent.** The primary agent is checked with the
ordinary agent rules; the other arms — the values of the `agent` factor — are
checked against the same registry and the same `required_capabilities`
(`agent_unknown`, `capability_unavailable`), because an agent factor selects
the adapter per variant and the primary agent's checks cover one arm only.

**Capability differences are recorded, not smoothed over.** Where two arms'
descriptors declare the same capability differently, the plan carries an
`agent_capability_difference` warning listing the capability and the two
statuses, and the report shows an unsupported field as unsupported instead of
as a zero (plan 6.5). That is what makes "Codex reports token usage, the fake
reports none" a fact of the report rather than an argument after the run.

A comparison normally runs `mode: direct`: naming a runtime would make the
experiment measure a runtime as well as the agents. It also normally declares
no `agent.config`, because a configuration written there is sent to every arm
while a parameter is declared by an agent, not by an experiment — `sandbox_mode`
belongs to Codex and to nothing else. Each arm starts from its own descriptor
defaults.

## `model_comparison`

One agent, one configuration, several requested models (plan 25, D) — and only
where the agent and runtime really allow the model to be steered.

**The `model` factor must vary**, or the plan is refused
(`comparison_without_factor`). **The model must be pinned**: an experiment
that runs through a runtime and neither sets `agent.config.model` nor varies
the model factor is refused (`model_not_pinned`), because an agent left to its
own default may be served something else entirely by the router under test —
measuring a configuration that was never declared.

The value space is the dimension's, which is the verified inventory of the
router under test plus the routing alias — not a general list of models
(`docs/DIMENSION_DESCRIPTORS.md`). And the distinction that keeps the type
honest: the `model` dimension records what was *asked for*; `routed_model`
records what *served*, observed only. A comparison over requested models is
read together with the per-run model evidence, which is why an alias such as
`auto_codex` is legal as a value and meaningless as a claim about a model
(`docs/RUNTIME_ADAPTERS.md`).

## `knowledge_replay`

The memory experiment of plan section 17: a learning arm that writes knowledge
while working tasks, a replay arm that works a task again in a new session with
read access to what the learning arm wrote, and a fresh control with no access
at all. Its own block declares the parts (`KnowledgeSelection`):

| Block | Meaning |
|---|---|
| `knowledge.plugin` | the plugin id, `agentic_knowledge` by default |
| `knowledge.learning.tasks` | at least one task uid the learning arm works |
| `knowledge.learning.write_enabled` / `read_enabled` | what the learning arm may do |
| `knowledge.replay.requires_readiness` | the replay waits for a confirmed knowledge base (default `true`) |
| `knowledge.replay.allow_unverified` | an explicit opt-in to replay anyway; the run is then recorded as unverified, never as verified |
| `knowledge.fresh_control` | always on; see below |
| `knowledge.scenarios` | the relation of each tested task to the learned knowledge |

The scenarios are `exact_replay` (the same task), `related_transfer` (a
neighbouring task) and `negative_transfer` (a task where earlier knowledge may
mislead). A transfer scenario that points at a task the learning arm worked is
rejected: exact replay measures recall, transfer measures whether the knowledge
moved at all, and a file that confuses them measures neither.

Four refusals are structural, and they are the difference between a memory
experiment and a story:

- a `knowledge` block on any other type is refused, and `knowledge_replay`
  without one is refused — the learning tasks, the gate and the scenarios are
  the experiment;
- `fresh_control` cannot be turned off: without the fresh arm a replay result
  is not attributable to knowledge rather than to a second attempt;
- at least one scenario is required, and scenario ids must be unique;
- the memory experiment must own the knowledge namespace it reads and writes,
  which in practice means a managed runtime, because the shared instance does
  not let the namespace be scoped (`docs/KNOWLEDGE_REPLAY.md`).

Retrieval is still not use: what a replay arm read and what it did with it are
measured separately, and the knowledge metrics stay `unavailable` while the
router exports no per-plugin signal (`docs/METRICS.md`).

## Choosing

- Something about the **configuration** changes, the agent stays: `configuration`.
- **Which system** works changes: `agent_comparison`.
- The **requested model** changes and nothing else: `model_comparison`.
- What changes is **what the agent was able to remember**: `knowledge_replay`.

The last one is the type that must not be improvised inside a configuration
experiment. Plan rule 16 forbids mixing configuration experiments with memory
learning experiments, and the type system is where that forbidden mixture
becomes a different `type:` rather than a subtle confound: an arm that learned
is not an arm that was configured differently.

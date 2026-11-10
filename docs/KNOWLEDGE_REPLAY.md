# Knowledge Replay

The research experiment of plan section 17: what does learned knowledge
contribute? It has three arms, and the comparison is only valid if the arms
differ in exactly one thing — the knowledge they see.

## The three arms

| Arm | Knowledge access | Session | Purpose |
|---|---|---|---|
| **learning** | read + write | new | work the learning tasks and produce the knowledge |
| **replay** | read (no write) | new, clean workspace | see the learning knowledge without its session history |
| **fresh control** | none | new, clean workspace | the same work with no knowledge at all |

Replay and fresh control must be identical in every other respect: the same
repository snapshot, task version, tests, evaluator, agent, parameters and
limits. The plan enforces this by giving every arm a fingerprint of the facts
that must be equal and refusing a difference by naming the key.

Only the learning arm writes. A replay that also wrote would feed its own
result back into the knowledge base, and a second replay would no longer
measure the first one.

## Scenarios

A scenario names what relationship the tested task has to the learned
knowledge:

- **exact_replay** — the same task the learning arm worked;
- **related_transfer** — a similar task it did not;
- **negative_transfer** — a task the knowledge is expected to mislead.

The plan validates the relationship: an exact replay must be a task in the
learning set, a transfer must be one that is not, and a task cannot play two
roles in one experiment.

## Readiness before a replay

The end of a session is not the end of the knowledge work: writes are
asynchronous and indexing runs in a separate worker. A replay started before
indexing settles measures a knowledge base that was not there yet, and the
result looks like a null effect of knowledge rather than a race.

So a replay is gated on a readiness check with an explicit status:

| Status | Meaning |
|---|---|
| `ready` | writes and indexing confirmed settled; the replay may run |
| `not_ready` | a probe looked and found the knowledge base still catching up |
| `unverified` | no probe could look, or it was overridden; the replay may run only with `allow_unverified` and is recorded as unverified |
| `unsupported` | this deployment cannot read the knowledge base at all |

On the shared external router the default status is `unsupported`: the router
refuses `/knowledge` reads and exports no per-plugin counter
(`docs/ROUTER_INTEGRATION.md` section 7). The gate blocks; `allow_unverified`
releases it and the run is recorded as `unverified`, never as verified.

## Isolation

A replay must not see anything of the learning arm except the knowledge. The
usual per-run workspace, session and context isolation is not enough; the
plugin's data spaces have to be isolated too. Whether the knowledge namespace
can be scoped is a property of the deployment, not of the experiment:

- on the **external** router the namespace is shared — every experiment on
  that instance sees the same knowledge base, which the plan reports as a
  warning (the arms stay distinguishable only because the fresh arm reads no
  knowledge, and two memory experiments on the instance contaminate each
  other);
- on a **managed** instance the harness owns the environment, so the namespace
  can be set per experiment.

## Scope: which checkout reads which collection

A memory experiment is only honest when the replay arm can read what the
learning arm wrote, and the plugin decides that with one fact about the
request: the repository scope. With the default strategy (``repo_basename``)
the scope key is the **basename of the working directory** the agent
declares — for a checkout, the name of its directory. Two consequences for
an experiment, and a fix for each:

* a replay must work under the same scope as the learning run, or it reads a
  collection that was never written. AK-Bench workspaces are named after the
  run, so the experiment runner pins a memory run's checkout to
  ``<run slug>/<repository name>``: the parent is unique per run, the
  basename is the fixture's name, and every arm that works the same fixture
  — the exact replay and every related-transfer twin of it — lands in the
  one collection the family's knowledge lives in. A non-memory experiment
  keeps the default run naming.
* a related transfer needs the *neighbouring* task to share the fixture's
  scope. It does, for the same reason: the pin is the fixture's name, not
  the task's. A family of tasks over one fixture is therefore a family of
  tasks over one knowledge base, which is the shape a transfer scenario
  needs and the shape the default naming would have broken.

The operator's own way is the plugin's scope override table, which maps a
declared path to a scope key before the basename is consulted (policy key
``scope.overrides``, applied per run on a managed instance through the
plugin's configuration). The pin and the override table are the same idea at
two levels; the harness applies the pin so an experiment author does not
have to, and documents the override table for checkouts the harness does not
name.

## Retrieval is not utilization


The plan measures the two separately. That the plugin retrieved knowledge is
not the same as the agent using it; a hit rate without a utilization signal is
half a measurement, and both stay `unavailable` until the router exports the
events that would support them.

## CLI

| Command | Description |
|---|---|
| `akbench knowledge plan [FILE] [--allow-unverified] [--json]` | build the memory plan: arms, shared fingerprints, readiness gate, isolation |
| `akbench knowledge readiness [--session FILE] [--json]` | what this deployment can say about a knowledge base before a replay |

## Shipped examples

`configs/experiments/knowledge-replay.yaml` is the minimal one-task memory
experiment. `configs/experiments/knowledge-replay-atlas.yaml` is the
family-shaped one: a learning arm on a five-module regression, and replay
and fresh controls for the same task plus three single-defect twins of the
same store, one per module. The twins are where the measurement lives: their
defects are in different modules than the learning task's, so the knowledge
must move as principles — the invariants, the dead-ends, the placement —
not as a patch. The same memory experiment also runs on six configurations —
three requested models (two fixed and the routing alias), each once with the
knowledge plugin absent from the process and once present in it — so the
memory effect is measured once per routing decision rather than argued for
one, and the report's baseline is the fixed 27B model with no memory.

`configs/experiments/knowledge-replay-memory-suite.yaml` is the suite-shaped
one: four seeds (`atlas`, `tidewater`, `depweaver`, `walqueue`), six learning
tasks and seven twins, written so that the way to solve them is the way the
plugins work. The tasks share a design (`.plans/memory-suite-plan.md`,
`docs/DATASETS.md`, *The memory suite*):

- **antagonistic defect pairs** — the naive fix of one regression re-raises
  the same exception and message as the other, so a memoryless model
  oscillates while the plugin records a dead end, counts the loop and, once
  `loop_threshold` is reached, escalates the routed model;
- **the rule lives in one decision record** under `docs/adr`, written by
  symptom, in a corpus of incident notes that name the wrong module on
  purpose; `CONTRIBUTING.md` states the hierarchy of truth and the README is
  deliberately stale — the documentation map and the `doc_type`-filtered
  hits are what make the record reachable;
- **procedures** — the new features need a repository tool run with specific
  flags (regenerate, lock a manifest, verify goldens or trace digests), stated
  in a guide and nowhere in the README; the session that did it once leaves a
  playbook;
- **long traces** — a digest or an offset found in the first phase is
  asserted in the last, which is what the compaction archive keeps;
- **twins with one signature** — a related twin where the recipe fits as it
  is, a related twin where only the principle transfers, and a negative twin
  where the same signature has a different cause and the recipe is a trap.

The suite runs on seven configurations, and **the environment is part of the
arm**: the plugins ship with loop escalation, the routing plugin's session
memory and a 200-file documentation budget switched off or too small, so the
arms that measure them declare them under `runtime_env`
(`LLM_ROUTER_KNOWLEDGE_AGENTIC_ESCALATION_ENABLED` through the
`knowledge_escalation_enabled` dimension; `..._ARCHIVE_ENABLED`,
`..._DOCS_ENABLED`, `..._DOCS_AUTO_INDEX`, `..._DOCS_CONTEXT_ENABLED`,
`..._DOCS_MAX_FILES`, `..._LOOP_THRESHOLD`,
`LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_ENABLED` directly). One
ablation arm keeps the knowledge plugin and turns everything beyond the mined
recipes off, so each mechanism's share can be read off the matrix: pairs
(1,4), (2,5), (3,6) isolate the memory under one routing decision, (6,7) the
mechanisms beyond recipes, (5,6) routing plus escalation on top of the same
knowledge.

## What is deliberately not here yet

- No live KB readback: readiness is a probe contract, and the default probe
  reports `unsupported` until a deployment can read the knowledge base.
- The plan does not run the arms: scheduling learning, replay and fresh runs
  (and persisting them) is the work of the storage and reporting phases.

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

## What is deliberately not here yet

- No live KB readback: readiness is a probe contract, and the default probe
  reports `unsupported` until a deployment can read the knowledge base.
- The plan does not run the arms: scheduling learning, replay and fresh runs
  (and persisting them) is the work of the storage and reporting phases.

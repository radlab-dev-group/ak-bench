# Agent adapters

The agent layer is the extensibility contract of AK-Bench (implementation plan,
section 6). The engine talks to **adapters**, never to agents. Everything
agent-specific — how a session starts, what a tool call looks like, where token
usage comes from — is confined inside an adapter, so adding an agent does not
change the runner, the scheduler, the evaluators or the experiment manager.

## The contract

`akbench/agents/contract.py` defines the surface the engine may use:

- **`AgentAdapter`** (a `Protocol`) — the eight operations of plan 6.2:
  `validate_environment`, `start_session`, `submit_task`,
  `wait_for_completion`, `get_status`, `collect_observations`, `cancel`,
  `close_session`. The contract is capability-aware: an operation the agent
  cannot support must fail loudly (the descriptor says `unsupported`), never be
  faked.
- **`AgentConfig`** — the experiment's agent-specific configuration, validated
  against the descriptor's `configuration_schema` before it reaches the
  adapter, plus `artifacts_dir` (where the adapter may write native logs) and
  `runtime` (the endpoint binding produced by the runtime layer).
- **`AgentSession`** — an opaque, adapter-owned handle. What "a session" means
  differs per agent class (process, HTTP conversation, service lease, routed
  thread), so the engine never inspects it (plan 6.5).
- **`AgentResult`** — the universal normalized result (plan 6.3).
  `result.as_dict()` emits exactly the JSON shape from the plan; fields the
  agent cannot provide stay `null` — nothing is ever guessed.
- **`AgentStatus` / `FailureClass`** — the shared vocabulary.
  `FailureClass` separates agent failures from infrastructure failures (plan
  rule 11) so a network blip is never scored against the agent.

## The registry and the catalog

- **`AgentRegistry`** (`akbench/agents/registry.py`) pairs an Agent Descriptor
  with an adapter factory and resolves agents by `id` and `version`, exactly
  like any other descriptor. Capability gating (`check_capabilities`) reads the
  descriptor, so the planner can reject an experiment that needs a capability
  the agent declares `unsupported` or `unverified`.
- **`ADAPTER_TYPES`** (`akbench/agents/catalog.py`) is the single registration
  point: it maps the `agent.adapter` id written in a descriptor to the class
  that implements the contract. Adding an agent means: add its descriptor,
  register its adapter here, pass the contract tests. Nothing in the runner
  changes.

## The Codex adapter

`akbench/agents/codex.py` implements the `codex_cli` adapter (execution type
`process`). It encodes the recipe verified in phase 0
(`docs/AGENT_INTEGRATION.md`):

- one `codex exec` process per task, each with a **private `CODEX_HOME`**,
  because that directory also holds the agent's own databases — isolating the
  directory is what makes isolation meaningful;
- the model provider is configured inside that `CODEX_HOME` through `env_key`,
  so the agent starts with no interactive login;
- `--json` gives a flat event stream (`thread.started`, `turn.completed`,
  `turn.failed`, `item.completed`, `error`);
- the session rollout under `CODEX_HOME/sessions` is the stable source for
  cumulative token usage, tool calls and the model/sandbox actually applied.

Values the CLI does not report stay `null`: cost in particular is never derived
(the descriptor marks `cost_usage: unsupported`).

## Contract tests

Every adapter must pass the shared suite in `tests/contract/` before an
experiment may be recorded as `valid` (plan 6.8). The suite covers:
configuration validation, start, workspace binding, task submission, completion
detection, timeout, cancellation, session close, status normalization,
observation collection and the handling of unavailable metrics.

It runs against:

- **the reference fake adapter** (`tests/contract/fake_agent.py`) — the
  smallest implementation of the contract, proving it is implementable without
  any knowledge of a real agent;
- **the real Codex adapter against a CLI stub**
  (`tests/contract/stubs/codex_stub.py`) — the production adapter, with only
  the CLI stubbed, so event parsing, rollout reading, timeout escalation and
  cancellation are all exercised without an agent or a network;
- **the real CLI, opt-in** (`tests/contract/test_codex_live_contract.py`) —
  end to end against the router; skipped unless `AKBENCH_RUN_LIVE=1`.

## Running an agent

`akbench agent run` is the generic runner: it resolves the agent from the
descriptor registry, instantiates its adapter through the catalog, validates
the configuration against the descriptor, prepares the workspace and drives the
run through the contract only. It contains no knowledge of any concrete agent.

```bash
# run a task from a prepared workspace
akbench agent run codex --workspace data/workspaces/task-workspace \
    --task-file task.txt --param sandbox_mode=workspace-write

# or prepare the workspace from a dataset task (mutation included)
akbench agent run codex --task wordcount-001 --runtime llm-router \
    --param sandbox_mode=workspace-write --json
```

`--param name=value` is repeatable; each name must be declared controllable by
the agent descriptor, and unknown names are rejected. `--runtime` binds the
agent to a runtime endpoint (base URL and credential) without naming the agent.

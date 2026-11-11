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
akbench agent run codex --task wordcount-001 --runtime llm-router-external \
    --param sandbox_mode=workspace-write --json
```

`--param name=value` is repeatable; each name must be declared controllable by
the agent descriptor, and unknown names are rejected. `--runtime` binds the
agent to a runtime endpoint (base URL and credential) without naming the agent.

## The reference adapter (`fake`)

`akbench/agents/fake.py` is the `fake` adapter (execution type `process`).
It is a deterministic implementation of the contract whose only purpose is to
say what the contract requires and to give CI and the agent comparison a
second agent that costs nothing and never flakes. It starts no process, opens
no socket and reports no model.

Its behaviour is scripted through the controllable `behaviour` configuration
parameter, which an experiment may set per run:

- `complete` (alias `solve`) — the run completes and a workspace marker is
  written;
- `noop` — the run completes without touching the workspace;
- `hang` (alias `timeout`) — the run never finishes on its own; only a timeout
  or a cancel ends it;
- `fail` — the agent failed; `infrastructure_error` — the environment failed,
  a different status and a different blame (plan rule 11).

Everything it reports is a fact about itself: the token pair is a fixed pair of
declared numbers, the cost is `unsupported` and stays `None`, and the version
is `fake-agent 1.0` unless disabled. Its descriptor
(`descriptors/agents/fake.yaml`) marks every capability `verified` because it
is our own protocol, with `cost_usage: unsupported` as the declared exception.

The adapter is registered in `agents/catalog.py` like any other, so an
experiment can name the agent `fake` by id. The contract suite in
`tests/contract/test_fake_agent_contract.py` covers the full shared contract
plus the per-run scripting and the alias resolution.

## The HTTP adapter (`http`)

`akbench/agents/http.py` is the `http` adapter (execution type `http`): the
reference implementation of the "agent API" class, for an agent that lives
behind an endpoint instead of a local process. It is stdlib-only and speaks
AK-Bench's own protocol — the four requests below are the contract an agent
server has to fulfil to be benchmarkable. No vendor product is assumed to speak
them; one that exposes something else needs its own translating adapter,
verified against that product's documentation (plan 29.10). Nothing about a
product is invented here.

### The agent-server protocol

| Request | Purpose | Response |
|---|---|---|
| `POST /tasks` | open a session and hand over the task | `201` `{"session_id": str}` |
| `GET /sessions/{id}` | liveness and state | `200` `{"state": str, "detail": str \| null}` |
| `POST /sessions/{id}/cancel` | ask the server to stop | `200`; `405` when the server cannot cancel |
| `GET /sessions/{id}/result` | the outcome in the universal shape (plan 6.3) | `200` (shape below) |
| `GET /version` | optional | `200` `{"version": str}` |

`POST /tasks` sends `{"task": str, "workspace": str \| null, "parameters":
dict}`; the workspace path is a suggestion — the server decides whether it
works in it, which is why the descriptor marks `workspace_binding: partial`.
The `state` vocabulary is `pending`, `running`, `completed`, `failed`,
`timeout`, `cancelled`, `infrastructure_error`; any other value is a protocol
violation, not a status.

`GET /sessions/{id}/result` answers with the fields the universal result
carries:

```json
{
  "status": "completed",
  "final_message": "done",
  "exit_code": 0,
  "workspace_changes": ["changed.py"],
  "observations": {"tool_call_count": 3},
  "artifacts": {"server_log": "server.log"},
  "token_usage": {"input_tokens": 21, "output_tokens": 9, "total_tokens": 30}
}
```

Token usage is passed through exactly as the server reports it; a server that
does not report it leaves the field `null` and the adapter fills nothing in.
Cost is never inferred and stays `None`.

### What the adapter promises

- **Workspace** — the local workspace path is sent with the task and the
  server decides; the adapter never claims control it does not have.
- **Cancellation** — `POST /sessions/{id}/cancel` is the request; a server
  that answers `405` is still reported `cancelled`, because the adapter asked.
- **Failure class** — an unreachable server, an HTTP `5xx` or a malformed body
  is an infrastructure error and never an agent failure (plan rule 11); a task
  the server itself failed is the agent's.
- **Observability** — the full request/response exchange of a run is written
  as the `http_exchange` artifact, so a run is auditable against the protocol.

The contract suite in `tests/contract/test_http_agent_contract.py` runs the
adapter against a real loopback stub server
(`tests/contract/stubs/agent_server_stub.py`) rather than a mock, so a green
run proves the documented protocol is implementable.

## The agent comparison

An `agent_comparison` experiment varies the agent and nothing else: the same
task, the same dataset version, the same evaluator, with the agent as a real
factor. Each arm starts from its own descriptor defaults, and the planner
checks every arm against the same rules as the primary — the agent must be
described, and it must provide the required capabilities. What the arms differ
on is recorded rather than smoothed over: a capability one agent declares
`unsupported` that another declares `verified` is reported as
`agent_capability_difference`, so the report shows an unsupported field as
unsupported instead of as a zero (plan 6.5, F3).

The experiment `configs/experiments/agent-comparison.yaml` compares `codex`
against `fake` on the `wordcount-001` task. The report of a comparison adds an
"Agent comparison" section: one row per agent, over every run that experiment
recorded for it, with the same numbers the configuration ranking states, and a
measure an agent never reported stays "not measured" rather than becoming a
zero. An experiment with one agent renders no such section at all.

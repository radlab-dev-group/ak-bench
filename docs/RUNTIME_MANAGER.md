# Runtime Manager

A runtime is an optional layer between an agent and its model (implementation
plan, sections 7 and 13). The agent itself never knows about the router; the
runtime manager is a per-runtime adapter that knows how to reach, observe and —
when possible — control one concrete runtime.

## Execution modes (plan 7.1)

An experiment declares how the agent reaches its model:

- **`direct`** — no runtime. The agent is configured to talk to its model
  itself. The planner produces no binding, and naming a runtime in this mode is
  an error.
- **`runtime`** — the agent is driven through an intermediate runtime.
- **`router`** — model requests pass through a router (the LLM Router is the
  first implementation).

`akbench runtime` and the `--mode` option of `akbench agent run` make the mode
explicit. A wrong combination is rejected with the reason: an experiment that
believes it is routed but is not would produce unusable results.

```bash
akbench agent run codex --task wordcount-001 --mode router --runtime llm-router
akbench agent run codex --task wordcount-001 --mode direct
```

## The manager contract

`akbench/runtime/contract.py` defines the operations of plan 7.2:
`start`, `stop`, `healthcheck`, `apply_configuration`, `read_configuration`,
`verify_configuration` and `collect_runtime_state`. The contract is
capability-aware: an operation a runtime cannot support raises
`CapabilityNotSupported` with the reason, never a fake result.

## The configuration triad (plan 13)

A run records how much of its runtime configuration was actually confirmed:

```json
{
  "requested_config": { "active_models": ["model-a"] },
  "effective_config": null,
  "observed_config": { "served_models": ["model-a", "model-b"] },
  "verification_status": "unsupported",
  "notes": ["the effective configuration is not readable over HTTP (403 by policy)"]
}
```

- **`requested`** — what the experiment asked for;
- **`effective`** — what the runtime actually applies, read from the runtime
  itself (never from the request);
- **`observed`** — what AK-Bench could actually confirm;
- **`verification_status`** — `verified`, `unverified` or `unsupported`.

Silence is never a pass: when a configuration cannot be read, the status says
so and `effective_config` stays `null`.

## The LLM Router adapter

`akbench/runtime/llm_router.py` implements the `llm_router` adapter. Every
claim is from `docs/ROUTER_INTEGRATION.md`:

- `GET /health` answers `200` with `{"body":"healthy",...}` — the only usable
  healthcheck;
- `GET /v1/models` lists the served models, but not aliases (`auto_codex` works
  and is absent), so the inventory is not the whole value space of the model
  dimension;
- the effective configuration is not readable over HTTP (`/config` and friends
  are denied by policy), so `read_configuration` reports `unsupported` unless a
  host-side model configuration file (`--config-file`) is configured and
  readable — then it reports `verified`;
- there is no configuration write endpoint, so `apply_configuration` refuses
  with the reason;
- **external** instances are shared: AK-Bench never starts, stops or
  reconfigures them (plan 13). **managed** instances are started with a
  configured command and health-checked until ready.

```bash
akbench runtime list
akbench runtime health llm-router
akbench runtime models llm-router
akbench runtime config llm-router            # reports the trust level
akbench runtime config llm-router --config-file /path/to/models-config.json
akbench runtime state llm-router
```

## What is intentionally not faked

- Reading the effective configuration over HTTP → `unsupported` (verified 403).
- Per-run plugin control on a shared instance → not available (plan 13: a
  `managed` instance is required).
- Per-plugin metrics → the router exposes none, so knowledge metrics are
  `unavailable`, never zero (see `docs/ROUTER_INTEGRATION.md` section 7).

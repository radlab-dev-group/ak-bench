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

## Self-start (managed) LLM Router

A runtime whose `supported_lifecycles` is `[managed]` and which declares a
`managed` launch block is **owned by the run**: AK-Bench starts it before the
agent and stops it when the run ends, and the run keeps the evidence.

The launch block is declared in the descriptor, not in the experiment:

```yaml
runtime:
  adapter: llm_router
  supported_lifecycles: [managed]
  base_url: http://127.0.0.1:8085
  managed:
    command: ["/usr/bin/python3.11", "-m", "llm_router_api.rest_api", "--gunicorn", ...]
    cwd: /path/to/llm-router
    env:
      LLM_ROUTER_MODELS_CONFIG: resources/configs/models-config.json
      LLM_ROUTER_AUTH_ENABLED: "false"
    factor_env:
      knowledge_enabled: LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED
    config_file: /path/to/models-config.json
    ready_timeout: 180.0
    stop_grace: 20.0
    log_file: router.log
```

What this buys, and what it means:

- **The command is the process itself.** AK-Bench holds the gunicorn master and
  stops it with SIGTERM, so the router cannot outlive the run. A launcher that
  daemonizes or supervises the server (`llm-router server start`) would leave a
  process AK-Bench can neither see nor stop, which is exactly why the managed
  command execs `python -m llm_router_api.rest_api`.
- **Environment is applied, not requested.** `managed.env` is static
  configuration; `factor_env` maps an experiment factor to the variable that
  carries it; and a combination may declare its own launch environment under
  `runtime_env`, which is applied last. A run whose variant is
  `knowledge_enabled: false` therefore runs against a router process that was
  started with `LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED=false`, and an arm that
  wants no knowledge plugin starts its process without it in
  `LLM_ROUTER_UTILS_PLUGINS_PIPELINE`. On the shared instance the same arm
  could only record that it asked. Precedence, from lowest to highest: the
  ambient environment, `managed.env`, the factor-mapped values, then the
  variant's `runtime_env`.
- **The pipeline is a launch decision, not a request.** Which plugins a router
  process loads is read when it starts; nothing told to a running process
  changes that. A pipeline in `managed.env` would load its plugins in every
  run of the runtime, so the shipped descriptor declares none and each arm of
  `llm-router-selfhost-fast.yaml` names the pipeline of its process. The run
  record keeps the declared environment as `runtime_environment`, with values
  whose names mark them as secrets reported by name only.
- **The log is an artifact of the run.** The launched process's standard output
  is written to `managed.log_file` inside the run's artifacts directory,
  registered like every other artifact, and downloadable from the report.
- **Restarting is the configuration write.** The router still exposes no
  configuration write endpoint; a managed instance changes configuration by
  dying and being started again with different environment. That is why
  `configuration_write` stays `unsupported` even when `per_run_plugin_control`
  is `verified`.
- **The state outlives the process.** Stopping the router does not empty Redis
  or the vector engine; a separate prefix (declared in `managed.env`) keeps a
  benchmark from reading the shared instance's collections, but it does not
  create isolation by itself.
- **No credential is needed.** The managed instance runs with
  `LLM_ROUTER_AUTH_ENABLED=false` (declared in `managed.env`), so the
  descriptor declares no `required_env` and the agent binding carries no
  `env_key`: codex sends no Authorization header and the router never checks
  one. A run therefore does not depend on an exported key — including a
  dummy that would only be a lie.

The shipped instance is `descriptors/runtimes/llm-router-ak-bench.yaml`, and
`configs/experiments/llm-router-selfhost-fast.yaml` is the self-hosted twin of
`llm-router-external-fast.yaml`: the same tasks and arms, but each run starts
its own router, so the knowledge arm is a configuration of a process the run
owned.

### What a run records from the instance it owned

A run that started its own instance keeps, in its record, the evidence that
instance gave it, and the report's plugin and model verification rests on
those fields:

- `runtime_environment` — the environment the process was launched with
  (descriptor `env`, factor-mapped values and the combination's `runtime_env`).
  A plugin toggle observed from this environment was **applied by the run**:
  the report says `unverified` with that note rather than `unsupported`,
  because the value is known and only the plugin's own confirmation is
  missing. A run against a shared instance has no such environment, and there
  `unsupported` stays the honest state.
- `served_models` — the inventory the instance answered with on
  `GET /v1/models`. It says what the instance *can* serve and never which
  model served the run, so it can never verify the pairing by itself.
- `model_evidence` — the instance's log, read after the run, naming what it
  handled: the models it received, the routing decision and the model each
  request was forwarded to. This is the only per-request evidence the router
  gives, so a requested model the log names is `verified` (an alias is
  verified as an alias, with the resolved model recorded), a model the log
  never names is a `mismatch`, and an instance that gave no log or no
  inventory is recorded as having given none.

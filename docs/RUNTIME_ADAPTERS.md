# Runtime adapters

A runtime adapter is the per-runtime half of plan section 7: one class that
knows how to start, stop, healthcheck and verify one concrete runtime, so the
engine can treat the router, a local runtime and a future managed instance as
the same object at the call sites. `docs/RUNTIME_MANAGER.md` covers the
execution modes and the configuration triad; this page is the adapter layer
itself — the contract, the two lifecycles, how a factor value becomes a real
process configuration, and how the model a run was served by is read from the
instance's own log.

## The contract

`src/akbench/runtime/contract.py` defines `RuntimeManager`, a `Protocol` with
the seven operations of plan 7.2 plus two identity attributes:

| Operation | Meaning |
|---|---|
| `start` | Start a managed instance. A no-op is not allowed: for an external runtime it raises `CapabilityNotSupported` instead, because silently doing nothing would read as "started" |
| `stop` | Stop the managed instance (SIGTERM, then a grace period) |
| `healthcheck` | Whether the runtime answers its health endpoint |
| `apply_configuration` | Push a configuration where the interface allows it |
| `read_configuration` | Read the effective configuration back, with its trust level |
| `verify_configuration` | Compare the effective configuration with an expectation |
| `collect_runtime_state` | A point-in-time snapshot: health, base URL, lifecycle, model inventory, metrics availability |

The contract is capability-aware: an operation the runtime cannot support
raises `CapabilityNotSupported` after the descriptor has declared it, instead
of being faked. The two supporting types are `RuntimeConfigReport` (the
requested/effective/observed triad plus `verification_status`) and
`RuntimeState` (the snapshot), both of which serialize with `as_dict()`.

`direct` mode is represented by no runtime at all: `plan_execution` in
`src/akbench/runtime/registry.py` returns a `RuntimePlan` whose runtime and
binding are `None`, and no manager is instantiated for it. A wrong
combination — `direct` naming a runtime, or `runtime`/`router` naming one that
does not support the mode — is an error, not a silent downgrade.

## The two lifecycles

`Lifecycle` has two values, and the difference between them is who owns the
process (plan 7.2, 13):

- **`managed`** — AK-Bench owns the instance. `start()` runs the
  descriptor's `managed.command` (see below) with this run's environment,
  waits for the health endpoint up to `ready_timeout`, and `stop()` takes it
  down with SIGTERM plus a `stop_grace`. A managed start refuses to begin when
  something already answers the configured `base_url`: a readiness probe that
  would pass on a foreign process would make the run measure an instance it
  did not start.
- **`external`** — a shared instance. AK-Bench never starts, stops or
  reconfigures it; `start()` and `stop()` raise `CapabilityNotSupported` with
  the reason, and the manager only observes (`healthcheck`,
  `read_configuration`, `collect_runtime_state`). A plugin toggle against it
  is recorded as requested, not applied.

A Runtime Descriptor (`src/akbench/descriptors/runtime.py`) declares
`supported_lifecycles`, `capabilities` (each with an evidence-backed status),
`required_env` and — when `managed` is supported — a `managed` block with
`command`, `cwd`, `env`, `factor_env`, `config_file`, `ready_timeout`,
`stop_grace` and `log_file`. Declaring `managed` without declaring the
`managed` lifecycle is a descriptor error: nothing would ever start it.

The only shipped adapter is `LlmRouterAdapter` (`src/akbench/runtime/llm_router.py`,
adapter id `llm_router`), registered through `RuntimeRegistry` alongside the
descriptors in `descriptors/runtimes/`. Its option resolution is explicit: an
option passed by the caller wins over the descriptor, and an unset one never
erases what the descriptor declares.

## How a factor value becomes a process configuration

The gap a runtime adapter closes is the one between *asking* for a
configuration and *applying* it. A factor value that reaches the router in a
request is a request; the same value in the environment of a process this run
started is a configuration. The mapping is declared, not invented:

- The **runtime descriptor** names the variable per factor: `managed.factor_env`
  is `factor id -> environment variable` (for example
  `knowledge_enabled: LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED`).
- The **planner** resolves the factor to a dimension and checks that it is
  controllable and that its `source` is the plugin's env
  (`plugin.<id>.env`), and that a `factor_env` line exists for it — otherwise
  the value has nowhere to go and the plan says so.
- The **orchestrator** hands the run's factor values to the adapter.
- The **adapter** applies them in a fixed order, lowest to highest
  (`LlmRouterAdapter._declared_values` / `process_environment`):

  1. the ambient environment (the operator's shell and its credentials);
  2. the descriptor's static `managed.env`;
  3. the factor-mapped values (`factor_env` × this run's factor values);
  4. the run's declared `runtime_env` — the environment the variant stated
     verbatim for its process, applied last because it is the most specific
     statement of what this arm is.

Two of those declarations come from the experiment, and they are different
instruments:

- `factors.combinations[...].runtime_env` (a `custom_matrix` combination) is
  per arm: the planner strips the reserved key from the factor values, hashes
  it into the variant's identity, and the run's instance starts with it.
- `execution.runtime.env` is per experiment: for a matrix the strategy
  expands (there is no combination to hang the declaration on), it is applied
  to every arm's instance.

Both are refused against a runtime the run does not start
(`runtime_environment_needs_managed`): an environment sent nowhere is not a
configuration. The values are strings — a YAML boolean is rejected by the
descriptor rather than reaching a process as `True` — and the environment a
run declared is recorded in the run record as `runtime_environment`.

What the *record* keeps is `declared_environment()`: the three declared parts
only (descriptor env, factor-mapped values, `runtime_env`), never the ambient
shell, and values whose name marks them as secrets by name alone. The process
receives the declared values verbatim; masking is a property of the record,
never of the process.

## Model verification from the instance log

The model a run *asked for* is an agent parameter. The model that *served* it
is a fact only the runtime can state, and only for a process this run started
(`LlmRouterAdapter.model_request_evidence`):

- An **external** instance reports no evidence at all, with the reason: the
  log of a shared instance cannot be attributed to one run.
- A **managed** instance logs verbosely into the run's artifacts
  (`managed.log_file`, placed in the run's directory by the runner), and the
  adapter reads its tail (8 MiB) for the router's own account of each request:
  which model it received (`Overriding trigger model: …`), which its routing
  chose (`Codex routing: … model=…`) and which one it forwarded to
  (`Request model … with config id`). The result is
  `served_models`, `routing_decisions` and `received_models`, or
  `available: false` with the reason when there is no log to read.

The orchestrator collects that evidence while the run still owns the process
and its log — before `stop()` — and records it in the run as
`model_evidence`, next to `served_models` from the `/v1/models` inventory.
The inventory is the weakest model evidence there is: it says what an
instance *can* serve, not what served the run, so it can never verify the
pairing on its own. A requested model the log names is verified; an alias is
verified as an alias with the resolved models recorded; a model the log never
names is a mismatch.

## The instance log as run evidence

The same log that verifies models is also the run's audit trail. The
descriptor names the file (`log_file`), the runner decides where it lands
(`log_dir`, the run's artifacts), so the log of a managed instance is an
artifact of the run that started it rather than a file somebody has to go
find. The shipped managed descriptor logs at DEBUG with verbose payloads,
which is why it is a local instance and why its log is treated as run
evidence, not as something to publish — the export screens what it may carry
(`docs/EXPORT.md`).

## What an adapter does not do

- It does not change the configuration of an instance it does not own; the
  shared instance refuses configuration reads and writes over HTTP (verified),
  so a factor aimed at it is refused at planning, not applied at run time.
- It does not guess: an unreadable configuration keeps `effective` at `None`
  and says why; an unattributable log reports `available: false`.
- It does not outlive the run: a managed instance dies with its run, and
  anything that survives the process (the knowledge state in Redis and the
  vector engine) is named in the descriptor's notes rather than pretended
  away.

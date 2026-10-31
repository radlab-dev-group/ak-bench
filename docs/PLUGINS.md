# Plugin Configuration and Observability

AK-Bench measures plugins the way it measures everything else: through a
descriptor that declares what may be observed, and an adapter that does the
observing (plan section 10). The experiment engine never learns a plugin's
environment variable names; it sees plugin state and metrics only.

## Principles

- **Allowlist only.** A plugin's environment is read exclusively through its
  descriptor's `observed_env` list. Nothing else is ever read, and the process
  environment is never scanned.
- **Secrets are presence.** A sensitive variable is recorded as `is_set` and
  its value is never stored, printed or exported.
- **Presence is not proof.** A variable being set is not proof the plugin
  works. Requested, configured, effective and observed values are stored
  separately, and `verification_status` says how much trust the other values
  deserve.
- **Unavailable is not zero.** A plugin metric that has no source is reported
  as `unavailable` with a reason. Reporting zero would claim "the plugin was
  not used", which the evidence does not support.

## The plugin descriptor

A plugin descriptor carries the identity, the provider, and a `benchmark:`
block that says how AK-Bench uses the plugin:

| Field | Meaning |
|---|---|
| `activation` | how the plugin is turned on (method + detail) |
| `verification` | which verification methods exist and whether they are required |
| `observed_env` | the allowlist of environment variables, each with type, role, and flags for `observed`, `dimension`, `controllable`, `sensitive` |
| `enabled_when` | the name of the `observed_env` entry that says whether the plugin is on |
| `metrics` | the plugin metrics the plugin is expected to produce |

`enabled_when` matters: a plugin's "is this on" answer must come from an
observed variable, not an assumption. A plugin without such a toggle cannot
report `enabled` honestly, so it is reported as `false` with a note that
activation is not observable.

## The plugin adapter

A `PluginAdapter` owns read/write/verify/interpret for one concrete plugin
(plan rule 10.3). The contract is small:

| Method | Responsibility |
|---|---|
| `supports(descriptor)` | whether the adapter can handle the plugin the descriptor describes |
| `observe(...)` | read the allowlisted inputs and build the per-run `PluginState` |
| `verify(...)` | run the plugin's verification and stamp the result |
| `normalize_metrics(...)` | return the declared metrics, measured only where evidence exists |
| `report(...)` | observe, verify and normalize in one call |

The shipped adapter, `LlmRouterPluginAdapter`, handles plugins that run inside
the LLM Router. It is honest about what that platform exposes today:

- the router refuses configuration reads, so an *effective* value cannot be
  obtained from a remote instance;
- the `/metrics` export carries no per-plugin counter, so no plugin metric can
  be attributed to one run.

Verification therefore happens only against evidence a caller injects:

- a **configuration reader** — a callable that returns the effective plugin
  configuration. On the shared external router this does not exist; on the
  router host it can be backed by a file (`--config-file`).
- a **metric source** — a mapping of measured metric names to values, for the
  day the router exports per-plugin counters.

Without either, the plugin is reported `unsupported` (a remote read the
platform cannot do) or `unverified`, and its metrics stay `unavailable` —
never faked.

## CLI

| Command | Description |
|---|---|
| `akbench plugin list [--json]` | the plugin descriptors this project ships |
| `akbench plugin status [REF] [--env NAME=VALUE] [--json]` | the observed configuration of each plugin, secrets as presence only |
| `akbench plugin verify [REF] [--config-file FILE] [--json]` | verify against available evidence and say what evidence is missing |

`--env NAME=VALUE` overrides one allowlisted variable for the check (a
dry-run), and `--config-file` supplies a host-side effective configuration so
a plugin can actually be verified where such a file exists.

## What is deliberately not here yet

- No per-plugin counter is scraped: the router does not export one, so plugin
  metrics are `unavailable` until that changes.
- No plugin is started or reconfigured: plugins run inside a router instance
  that AK-Bench observes, not one it owns.

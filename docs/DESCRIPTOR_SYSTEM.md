# Descriptor system (Phase 2)

Extensible components are defined by **descriptors**: versioned, validated
YAML documents. The engine reads only what a descriptor declares; it never
assumes a capability that is not recorded there, and it never simulates one
that is missing.

## Principles

1. **Addition without engine changes.** A new agent, runtime, plugin, model,
   category, evaluator, dimension or metric is a new file in the descriptor
   directory. Nothing in `src/akbench` needs to change.
2. **Versioned identity.** Every descriptor carries `schema_version`, `id` and
   `version`. The same `id` may exist in several versions; an experiment pins
   the exact digests of the descriptors it used, so editing a descriptor can
   never silently reinterpret historical results.
3. **Evidence-backed statuses.** Capability statuses use a fixed vocabulary —
   `verified`, `partial`, `unsupported`, `unverified`. `unverified` is
   deliberately *not* usable: an unchecked capability must be confirmed before
   a plan depends on it.
4. **No invented data.** Unavailable measurements are recorded as
   `unavailable` with a reason, never as zero or a guess.

## Kinds and layout

The directory name selects the kind; the file name is free.

| Kind | Directory | Example |
|---|---|---|
| agent | `descriptors/agents/` | `codex.yaml` |
| runtime | `descriptors/runtimes/` | `llm-router.yaml` |
| plugin | `descriptors/plugins/` | `agentic_knowledge.yaml` |
| model | `descriptors/models/` | `router_models.yaml` |
| category | `descriptors/categories/` | `bug_fix.yaml` |
| evaluator | `descriptors/evaluators/` | `pytest_evaluator.yaml` |
| dimension | `descriptors/dimensions/` | `model.yaml` |
| metric | `descriptors/metrics/` | `quality.yaml` |

Each file may contain a single mapping, a list of mappings, or a multi-document
YAML stream. Unknown keys are rejected: a descriptor that is silently ignored
looks configured when it is not.

## Registries

`DescriptorRegistry` is the in-memory store, keyed by
`(kind, id, version)`. It resolves `id` (newest version) or an exact
`id@version`, reports `versions` and `ids`, and exposes `digest_map()` — the
`kind:id@version -> sha256` table an experiment embeds in its record.

- `load_registry(root)` loads and validates every descriptor under `root`.
- `load_descriptor_file(path, kind)` validates one file alone, so `descriptor
  validate` can report per-file verdicts.
- Re-registering identical content is idempotent; the same `id@version` with
  different content is a **conflict** and is refused.

## ENV allowlist (plan 10.1)

A plugin descriptor's `benchmark.observed_env` is the only list of environment
variables AK-Bench may ever read. The process environment is never scanned.

- `observed` — the variable is read at all;
- `dimension` — it may be an experiment factor (implies `controllable`);
- `controllable` — AK-Bench may set it safely;
- `sensitive` — the value is recorded as `is_set` only, never captured.

`dimension` without `controllable` is a contradiction and is rejected, as is
any sensitive variable marked controllable.

## Dimensions (plan 11)

A dimension declares an experiment factor: type, value space, source,
`controllable`, `configure_via`, `verify_via` and dependencies. Derived
fact: `usable_as_factor` is true only for a controllable dimension with a
value space. Observed-only dimensions (e.g. `routed_model`) are recorded and
compared — they never generate variants, and a planner must reject them as
factors even if a configuration asks.

## CLI

```bash
akbench descriptor list [--kind KIND] [--json]
akbench descriptor validate [--kind KIND] [--json]   # exit 1 if any file is invalid
akbench descriptor show REFERENCE --kind KIND [--json]

akbench agent list [--json]
akbench agent inspect REFERENCE [--json]
akbench category list [--json]
```

`validate` checks every file independently, so one broken descriptor cannot
mask the verdict on the rest of the directory.

## What is deliberately not here yet

Task, experiment and environment descriptors belong to later phases (3, 8).
The runtime and plugin *adapters* that act on these descriptors (read/write
configuration, verify, interpret events) arrive with phases 5 and 9; until
then the descriptors describe the interface without anyone acting on it.

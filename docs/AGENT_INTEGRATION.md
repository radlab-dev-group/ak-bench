# Agent integration — spike results (Phase 0)

This document describes **only facts verified locally**. Every capability is
marked `verified`, `partial`, `unsupported` or `unverified`. Nothing here is a
guess.

## 0. Verification conditions

| Item | Value |
|---|---|
| Agent | Codex CLI `0.166.0` (`codex-cli 0.166.0`), standalone install |
| Binary path | `~/.local/bin/codex` → `~/.codex/packages/standalone/releases/0.166.0-x86_64-unknown-linux-musl/bin/codex` |
| System | Ubuntu 22.04, x86_64 kernel |
| Provider / runtime | LLM Router `http://192.168.100.65:8081/v1`, `wire_api = "responses"` |
| Model (requested) | `auto_codex` (trigger alias for agentic routing) |
| Verified on | 2026-10-30 |
| Prototype | `spike/run_spike.py`, output in `data/artifacts/spike/spike-20261030-130140/` |

Prototype outcome: status `completed`, evaluation `1 passed`, 96.7 s,
`input_tokens=39313` (`cached_input_tokens=21010`), `output_tokens=588`,
6 `exec_command` tool calls, session `01a18cb0-474a-7da3-9adf-3ae6967c6d69`.

## 1. Starting the agent

Non-interactive mode (one process = one task):

```bash
codex exec [OPTIONS] [PROMPT]
```

- A missing Git repository is an error; `--skip-git-repo-check` disables the check.
- Exit code: `0` on a clean finish. Agent errors and infrastructure errors
  **must be separated from the JSONL stream and stderr**, not from the exit code.
- `codex doctor` reports installation, authentication and CODEX_HOME database health.

## 2. Task submission

| Method | Status | Notes |
|---|---|---|
| `PROMPT` argument | verified | used in the spike |
| `stdin` (or `-`) | verified (CLI docs) | when combined with an argument, stdin is appended as a `<stdin>` block |
| `--output-schema <FILE>` | verified (docs) | forces a final answer matching a JSON Schema |
| `-o, --output-last-message <FILE>` | verified | writes the final message; used in the spike |

## 3. Workspace selection

- `-C, --cd <DIR>` — the agent's working directory. **verified** (used in the spike).
- `--worktree` — a Codex-managed Git worktree. `unverified` (not exercised;
  AK-Bench has its own Workspace Manager, see the conclusion in §12).
- `--add-dir <DIR>` — extra writable directories. `verified` (present in the CLI),
  semantics `unverified`.

## 4. Parameterization

| Parameter | Status | Notes |
|---|---|---|
| `-m, --model <MODEL>` | verified | passing `auto_codex` is accepted |
| `-c, --config key=value` | verified | TOML override, dotted paths, e.g. `-c approval_policy="never"` |
| `-p, --profile <NAME>` | verified (CLI) | layers `~/.codex/<name>.config.toml` |
| `--enable/--disable <FEATURE>` | verified (CLI) | shorthand for `-c features.<name>=…` |
| `--strict-config` | unverified | hard-fail behaviour not exercised |
| `--ignore-user-config` | verified | used indirectly through the isolated `CODEX_HOME` |
| `--ignore-rules` | unverified | not exercised |

## 5. Sessions and context isolation

- Every `codex exec` call creates a new thread/session — the identifier arrives
  in the `thread.started.thread_id` event. **verified**.
- Forcing a new session = a new process invocation without `resume`. **verified**.
- `codex exec resume <SESSION_ID>` / `resume --last` — continues the context. **verified (CLI)**.
- `codex exec fork` — a new session based on an existing one. **verified (CLI)**.
- `--ephemeral` — does not persist the session to disk. **verified (CLI)**;
  note: that also removes the rollout trace source (§8).
- There is no reset of an existing session — only resume/fork → `session_reset: unsupported`.

### 5.1. Isolated `CODEX_HOME`

Verified: pointing `CODEX_HOME` at an empty directory is enough to start the
agent **without logging in**, as long as the provider is configured through
`env_key`. In the spike the directory contained only a `config.toml` with the
provider and `env_key = "LLM_ROUTER_API_KEY"`.

Consequences for AK-Bench:
- `fresh_agent_session` and `clean_agent_context` are achieved with a separate
  process plus a separate `CODEX_HOME` per run;
- `CODEX_HOME` also holds databases (`state_*.sqlite`, `logs_*.sqlite`,
  `thread_history_*.sqlite`), so isolating agent memory means isolating the
  whole directory;
- no `[projects."…"] trust_level` entries are needed — with
  `approval_policy="never"` and `sandbox_mode="workspace-write"` the task
  started without trusting the directory. **verified**

## 6. Completion detection and status

The `codex exec --json` stream (JSONL, flat events — `type` at the top level):

| Event | Meaning |
|---|---|
| `thread.started` | session identifier |
| `turn.started` | turn begins |
| `turn.completed` | turn succeeded, carries `usage` |
| `turn.failed` | turn failed, carries `error` |
| `item.started` / `item.updated` / `item.completed` | items (see §8) |
| `error` | unrecoverable stream error |

Item types: `agent_message`, `reasoning`, `command_execution`, `file_change`,
`mcp_tool_call`, `web_search`, `todo_list`.

- Completion detection: `turn.completed` / `turn.failed` + process exit. **verified**
- Status of a running process: **no external API** — stream only.
  `status_query: partial`
- `codex app-server` / `agents` / `queue` (session control through a daemon)
  exist, but are **unverified** for benchmark use — they were not needed here.

## 7. Timeout and cancellation

- There is no timeout flag in the CLI. **verified (absent)**.
- Approach used: `SIGINT` to the process from an alarm (in the prototype),
  then `wait()`. The timeout path **was not covered** live (the run finished
  before the limit) → `cancellation: partial`.
- `SIGKILL` kills the process tree — trivial, but leaves the rollout unclosed;
  on retries such a run must be recorded as `infrastructure_error`, not
  `agent_error`.

## 8. Traces, tools, observations

Two independent sources:

1. **The JSONL stream** (`--json`): live items, including `command_execution`
   with `command`, `aggregated_output`, `exit_code`, `status`.
2. **The session rollout**: `CODEX_HOME/sessions/RRRR/MM/DD/rollout-<time>-<uuid>.jsonl`.

In the rollout (`type` + `payload` entries):

| Entry | Contents | Used by AK-Bench for |
|---|---|---|
| `session_meta` | `session_id`, `cwd`, `cli_version`, `model_provider`, `originator`, `base_instructions` | agent version, observed cwd, provider |
| `turn_context` | `model`, `cwd`, `approval_policy`, `sandbox_policy`, `permission_profile` | **observed configuration** |
| `response_item/function_call` | `name`, `arguments`, `call_id`, `status` | tool trace |
| `response_item/function_call_output` | tool result | correlating tool → effect |
| `response_item/message`, `/reasoning` | agent content, reasoning | qualitative analysis |
| `token_usage_record` | `usage`, `turn_token_usage`, `thread_token_usage` (cumulative) | tokens |
| `world_state` | world state | diagnostics |

In the spike: 6 × `exec_command`; tokens taken from `thread_token_usage`
(`total_tokens` is the sum of `input`/`output`).
`tool_trace: verified`.

## 9. Tokens and cost

- Token usage: `verified`. `usage` keys: `input_tokens`, `cached_input_tokens`,
  `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens`, `total_tokens`.
- **Cost: `unsupported`** — neither the stream nor the rollout contains any cost
  field (no occurrence of `cost*` anywhere in the rollout), and the router does
  not trust a per-run price list. AK-Bench must report
  `total_cost = null`/`unavailable`.
- `rate_limits` in the `token_count` event — **absent** in the spike (local
  provider), so limits cannot be based on them. `unverified` for OpenAI providers.

## 10. Model observation — the key limitation

- `turn_context.model` = **`auto_codex`**, i.e. an alias, not the real model.
- A parallel request to the router (`/v1/chat/completions`, `model: auto_codex`)
  returned `"model": "qwen/Qwen3.8-Flash-Next"` — routing works and **is visible
  in the `model` field of the chat/completions response**.
- Codex uses `wire_api = "responses"`, and the presence of a `model` field in
  the `/v1/responses` response was not verified → `model_observation: partial`.

Methodological consequence: with agentic routing, AK-Bench **cannot** determine
model usage from agent data. The source of truth is the router side (logs and
metrics), not the agent. This also applies to "Auto Codex ON/OFF" experiments.

## 11. File and network isolation

| Capability | Status | Notes |
|---|---|---|
| `read-only` / `workspace-write` / `danger-full-access` | verified | `-s`, default `read-only` |
| Network disabled by default in `workspace-write` | verified (docs: `sandbox_workspace_write.network_access`, default `false`) | |
| `CODEX_SANDBOX_NETWORK_DISABLED=1` in the process environment | verified (docs) | useful verification signal |
| `sandbox_workspace_write.writable_roots` | verified (docs) | extra writable roots |
| `--dangerously-bypass-approvals-and-sandbox` | verified (exists) | only exercised under external sandboxing |
| Docker as an AK-Bench layer | `unverified` in this phase | the Codex sandbox was sufficient; Docker checked separately (v29.2.1) |

## 12. Capability table for `codex_cli` (proposal for the Agent Descriptor)

| Capability | Status | Note |
|---|---|---|
| `workspace_binding` | verified | `-C` |
| `fresh_session` | verified | separate process + `CODEX_HOME` |
| `session_reset` | unsupported | resume/fork only |
| `task_submission` | verified | argument or stdin |
| `completion_detection` | verified | `turn.completed` / `turn.failed` |
| `status_query` | partial | stream of the current process only |
| `cancellation` | partial | process signals, no API |
| `token_usage` | verified | rollout + stream |
| `cost_usage` | unsupported | no data available |
| `tool_trace` | verified | rollout + `item.completed` |
| `model_observation` | partial | `auto_codex` alias; real model only on the router side |
| `streaming_output` | verified | `--json` |
| `filesystem_control` | verified | sandbox + `--add-dir` |
| `network_control` | verified | `sandbox_workspace_write.network_access` |
| `session_export` | verified | the JSONL rollout file |
| `structured_output` | verified (docs) | `--output-schema` |

## 13. Risks and inconsistencies found during the spike

1. **Knowledge contamination of experiments.** The current operator session goes
   through the same router with `agentic_knowledge` enabled, and the
   `<agentic_knowledge>` block was really injected into context (observed while
   working in this repository). The knowledge layer is scoped per repository, so
   benchmark runs in the same repository may inherit knowledge from the operator
   session. Enforced: a dedicated scope/KB for the benchmark, and verifying KB
   state before a run.
2. **The model alias hides routing** (§10).
3. **No cost** (§9) — the cost metric must stay `unavailable`, never zero.
4. **No timeout or cancellation at the agent level** (§7) — a real constraint
   for `retry_infrastructure_errors`.
5. **The rollout as a trace source is a side effect of session persistence**; it
   disappears with `--ephemeral`. An adapter must treat this as a critical
   dependency.

## 14. How to reproduce

```bash
# required: LLM_ROUTER_API_KEY in the environment
python3 spike/run_spike.py --dry-run          # prepare environments only
python3 spike/run_spike.py --timeout 420      # full E2E run
```

Artifacts: `data/artifacts/spike/<run_id>/` — `manifest.json`,
`codex_stdout.jsonl`, `codex_stderr.log`, `agent_trace.jsonl`,
`tool_calls.jsonl`, `diff.patch`, `last_message.txt`, `evaluation.json`.

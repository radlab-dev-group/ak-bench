# LLM Router integration — spike results (Phase 0)

Covers the LLM Router instance the spike runs were executed against. Describes
only what was checked in HTTP requests or in the code of
`/mnt/data2/dev/develop/llm-router` and `/mnt/data2/dev/develop/llm-router-plugins`.

## 0. Instance under test

| Item | Value |
|---|---|
| Address | `http://192.168.100.65:8081` |
| Instance lifecycle mode | **external** — shared instance, not managed by AK-Bench |
| Authentication | key in `Authorization: Bearer $LLM_ROUTER_API_KEY` |
| Agent-facing endpoints | `POST /v1/responses` (Codex, `wire_api = "responses"`), `POST /v1/chat/completions` |
| Router code | `llm-router` (`llm_router_api`); plugins: `llm-router-plugins` |

## 1. Healthcheck — verified

| Method and path | Response |
|---|---|
| `GET /health` | `200`, body `{"body":"healthy","status":true,"stream":false}` |
| `GET /healthz` | `403` — denied by the access policy |
| `GET /health/live` | `403` — denied by the access policy |

Only `GET /health` is usable as the benchmark healthcheck.

## 2. Model inventory — verified

`GET /v1/models` (code `200`) returns 6 models:

```text
google/gemma-4-12b-it
google/gemini-3.1-flash-lite-preview
google/gemma-4-12b-it-playground
qwen3-coder:30b
qwen/Qwen3.8-27B
qwen/Qwen3.8-Flash-Next
```

Note: `auto_codex` **does not appear** in this list even though it works as an
alias in requests. `/v1/models` is therefore not a complete picture of the
"model" dimension's value space.

## 3. Can the effective configuration be read? — NOT over HTTP

Checked and rejected (`403 Access to this endpoint is denied by policy`):

`/config`, `/admin/config`, `/routing/config`, `/knowledge/stats`, `/utils`,
`/version`, `/api_version`, `/v1/api_version`, `/list_models`.

The effective configuration is only reachable on the router host:

- model file: `LLM_ROUTER_MODELS_CONFIG` (default `resources/configs/models-config.json`),
  the `active_models` key is required;
- plugin configuration: `llm_router_plugins/resources/<type>/<plugin>.json`
  plus environment overrides.

Conclusion: in `external` mode AK-Bench **cannot verify** the effective
configuration of the router or its plugins. Per the plan's rule ("a
configuration is not considered active without verification"), experiments on a
shared router must be marked `unverified` unless file/log access on the host is
available.

## 4. Plugin pipeline — verified from code

| Item | Value |
|---|---|
| Pipeline activation variable | `LLM_ROUTER_UTILS_PLUGINS_PIPELINE`, e.g. `"agentic_routing_codex,agentic_knowledge"` |
| Registry | `llm_router_plugins.utils.registry.MAIN_UTILS_REGISTRY` |
| Plugin lifecycle | one instance per process; `apply(payload)` runs before guardrails and before provider selection |
| Ordering | the first plugin that overwrites `model` wins the dispatch; `agentic_knowledge` must run **after** routing |

## 5. The "Auto Codex" dimension (plugin `agentic_routing_codex`)

- Trigger: the `auto_codex` model alias backed by an `api_type: "builtin"` provider.
- ENV prefix: `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_`
  (including `…TRIGGER`, `…HEURISTIC_ENABLED`, `…SEMANTIC_ENABLED`).
  Names confirmed in code: `AGENTIC_ROUTING_PREFIX = "LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_"`,
  and the Codex prefix is `AGENTIC_CODEX_ROUTING_PREFIX = f"{AGENTIC_ROUTING_PREFIX}CODEX_"`.
- Proof of life — **verified**: a request with `model: "auto_codex"` returned
  `"model": "qwen/Qwen3.8-Flash-Next"` — routing replaced the model.

## 6. The "Knowledge" dimension (plugin `agentic_knowledge`)

| Item | Value |
|---|---|
| Registry key | `agentic_knowledge` |
| Class | `llm_router_plugins.utils.knowledge.agentic_knowledge.plugin.AgenticKnowledgePlugin` |
| ENV prefix | `LLM_ROUTER_KNOWLEDGE_AGENTIC_` (confirmed in `config.py`) |
| ENV flags (verified from code) | `ENABLED`, `READ_ENABLED`, `WRITE_ENABLED`, `ESCALATION_ENABLED`, `ARCHIVE_ENABLED`, `DOCS_ENABLED`, `DOCS_CONTEXT_ENABLED` |
| Default configuration | `llm_router_plugins/resources/knowledge/agentic_knowledge.json` |
| Indexing worker | `llm-router-agentic-kb-worker` |
| Dependencies | the SSE client (`sse_lib`) + Redis; without them the plugin loads and does nothing |
| Error policy | fail-open for traffic, fail-hard for an invalid policy (at startup) |

Facts that matter for Knowledge/Replay experiments:
- the plugin changes `payload["model"]` only when escalation fires, and appends
  a context block; the annotation lands in `routing.knowledge` **in the internal
  payload**, not in the HTTP response the agent sees;
- the end of an agent session is **not** proof that the KB is ready — indexing is
  asynchronous (worker), so Replay requires confirming that the write and index
  steps have finished first;
- real trace of knowledge at work: the injected `<agentic_knowledge>` block was
  visible in the context of the current operator session in this repository
  (anecdotal evidence, but from real traffic).

## 7. Metrics and plugin activity signals — a significant gap

`GET /metrics` (code `200`, Prometheus) contains, among others:

```text
http_requests_total, http_request_duration_seconds_*, http_request_size_bytes_*
http_request_exceptions_total, http_requests_in_progress
llm_router_provider_calls_total, llm_router_provider_error_total
llm_router_provider_latency_seconds_*, llm_router_model_fallback_total
llm_router_lb_strategy_selected_total, llm_router_retry_total
llm_router_tokens_total, llm_router_response_format_total
llm_router_pipeline_stage_total{result="success",stage="provider_resolved"}
guardrail_incidents_total, masker_incidents_total
```

- `llm_router_pipeline_stage_total` has **only** the `provider_resolved` stage.
- There are no per-plugin counters: neither `knowledge_retrieval_count`, nor
  `knowledge_write_count`, nor any `agentic_routing_codex` signal.

Conclusion: the current metric set is not enough to measure the Knowledge and
Auto Codex dimensions. One of the following is required:
1. enable router logging (`LLM_ROUTER_LOG_TO_FILE`, `LLM_ROUTER_LOG_LEVEL`) and
   parse the plugins' decision lines,
2. a custom plugin export into `/metrics`,
3. reading KB/SSE state directly.

Until one of them exists, knowledge metrics must be reported as `unavailable`,
never as zero.

**Measured indexing-lag observation (2026-10-30):** while working in this
repository, the injected document registry covered only `README.md` and the plan
file, even though two new `docs/*.md` files had been on disk for several
minutes. This confirms the plan's thesis: **KB readiness must be verified
separately**, and the window between a write and knowledge becoming available is
a measurable metric (`indexing_latency`).

## 8. Router runtime environment variables (verified from `docs/ENV_DEFINITIONS.md`)

| Variable | Default | Meaning |
|---|---|---|
| `LLM_ROUTER_MODELS_CONFIG` | `resources/configs/models-config.json` | model configuration file |
| `LLM_ROUTER_LOG_FILENAME` | `llm-router.log` | log file name |
| `LLM_ROUTER_LOG_LEVEL` | `INFO` | logging level |
| `LLM_ROUTER_LOG_TO_FILE` | `false` | also write logs to a file |
| `LLM_ROUTER_LOG_MAX_BYTES` | `52428800` | log rotation size |
| `LLM_ROUTER_LOG_BACKUP_COUNT` | `5` | number of rotated copies |
| `LLM_ROUTER_MINIMUM` | `False` | proxy-only mode |
| `LLM_ROUTER_IN_DEBUG` | `False` | debug mode (forces DEBUG) |
| `LLM_ROUTER_VERBOSE` | `False` | log raw, **unmasked** requests (PII!) |
| `LLM_ROUTER_AUTH_ENABLED` | `false` | enforce `sk-llmr-live-` key authentication |

`LLM_ROUTER_VERBOSE` is the only verified way to see full payloads (and thus the
`routing.knowledge` annotation), but it logs PII — acceptable for the benchmark
only in an isolated environment and with secret filtering.

## 9. Managed vs shared mode — a design decision

| Property | `external` (current) | `managed` (target for experiments) |
|---|---|---|
| Per-run plugin ENV control | impossible | full |
| Reading the effective configuration | impossible (403) | possible (file + logs) |
| KB state isolation | none | possible (separate Redis/SSE) |
| Risk of changes during a run | real | eliminated |
| Reproducibility | limited | required by the plan |

**Recommendation:** experiments with the Knowledge and Auto Codex dimensions
require a `managed` instance (own container + own Redis/SSE + own configuration
file). The shared router is fine for integration and smoke tests, but its
results must be marked `valid_with_warnings` or `invalid` depending on the
capabilities an experiment requires.

## 10. Integration status

| Capability | Status |
|---|---|
| Healthcheck | verified |
| Model inventory (`/v1/models`) | verified |
| Calling `chat/completions` through the `auto_codex` alias | verified |
| Agentic routing swaps the model | verified (response `model`) |
| Calling `/v1/responses` and observing the model in the response | unverified |
| Reading the effective configuration over HTTP | unsupported |
| Per-plugin metrics | unsupported |
| Starting/stopping the instance from AK-Bench | unverified (not implemented in Phase 0) |
| Per-run plugin ENV control | unverified (requires `managed`) |
| KB readiness (indexing finished) | unverified |

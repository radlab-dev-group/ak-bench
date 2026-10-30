# Phase 0 — integration spike

A tiny, self-contained prototype (Python standard library only) that confirms
the real integration capabilities of an agent and a router before the actual
platform is built.

## What it does

1. Creates an isolated workspace from the fixture repo (`spike/repo`) and initializes a Git repository.
2. Creates an isolated `CODEX_HOME` with a minimal `config.toml` (authentication via `env_key`, no login) — proof that `fresh_agent_session` + `clean_agent_context` are feasible.
3. Runs `codex exec --json` on the `spike/task.yaml` task with a timeout.
4. Parses the JSONL stream and the session rollout: session id, tokens, tool calls, observed model/sandbox.
5. Records the `git diff` and evaluates the result with pytest run **outside** the agent workspace (the hidden-test isolation pattern).
6. Writes a Reproducibility Manifest with artifact hashes and `requested` / `effective` / `observed` separated.

## Running it

```bash
# required: LLM_ROUTER_API_KEY in the environment
python3 spike/run_spike.py --dry-run       # prepare environments only
python3 spike/run_spike.py --timeout 420   # full E2E run
```

Artifacts land in `data/artifacts/spike/<run_id>/` (a Git-ignored directory).

## Outcome

The verified facts are documented in `docs/AGENT_INTEGRATION.md` and
`docs/ROUTER_INTEGRATION.md`. Evidence of the last successful run (manifest,
diff, evaluation, tool calls) lives in `spike/evidence/`.

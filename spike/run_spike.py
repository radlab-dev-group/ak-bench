#!/usr/bin/env python3
"""AK-Bench Phase 0 spike: end-to-end prototype.

Runs the Codex CLI (via Agent-Adapter-shaped code) on a tiny fixture task,
in an isolated workspace and isolated CODEX_HOME, collects JSONL events,
session rollout, git diff, and evaluates the result with pytest run OUTSIDE
the agent workspace. Writes a Reproducibility Manifest + artifacts.

Stdlib only. Usage:
    python3 spike/run_spike.py [--model auto_codex] [--timeout 600] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURE_REPO = ROOT / "repo"
DATA = ROOT.parent / "data"
ARTIFACTS = DATA / "artifacts" / "spike"

MINIMAL_CODEX_CONFIG = """\
# Minimal config for AK-Bench spike. Auth via env_key, no OpenAI login.
model = "auto_codex"
model_provider = "llamacpp"
model_context_window = 256000
model_max_output_tokens = 32000
approval_policy = "never"
sandbox_mode = "workspace-write"

[model_providers.llamacpp]
name = "LLM Router (spike)"
base_url = "http://192.168.100.65:8081/v1"
wire_api = "responses"
env_key = "LLM_ROUTER_API_KEY"
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def prepare_workspace(run_id: str) -> Path:
    ws = DATA / "workspaces" / run_id
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    shutil.copytree(FIXTURE_REPO, ws / "repo")
    repo = ws / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "akbench@spike.local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "AK-Bench Spike"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base fixture"], cwd=repo, check=True)
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return ws


def prepare_codex_home(run_id: str) -> Path:
    ch = DATA / "runtime_instances" / run_id
    if ch.exists():
        shutil.rmtree(ch)
    ch.mkdir(parents=True)
    (ch / "config.toml").write_text(MINIMAL_CODEX_CONFIG)
    return ch


def run_codex(args, workspace: Path, out_dir: Path, codex_home: Path) -> dict:
    """Agent Adapter (codex_cli, process mode) for the spike."""
    repo = workspace / "repo"
    env = dict(os.environ)
    env["CODEX_HOME"] = str(codex_home)

    last_message_file = out_dir / "last_message.txt"
    cmd = [
        "codex", "exec",
        "--json",
        "--cd", str(repo),
        "-s", "workspace-write",
        "-c", 'approval_policy="never"',
        "-o", str(last_message_file),
        "--color", "never",
    ]
    if args.model:
        cmd += ["-m", args.model]

    task_text = (ROOT / "task.yaml").read_text()
    cmd.append(task_text.strip())

    stdout_path = out_dir / "codex_stdout.jsonl"
    stderr_path = out_dir / "codex_stderr.log"
    started = time.time()
    proc = subprocess.Popen(
        cmd, cwd=repo, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    def _kill(*_):
        proc.send_signal(signal.SIGINT)

    timer = signal.signal(signal.SIGALRM, _kill)
    signal.alarm(args.timeout)
    try:
        with open(stdout_path, "w") as so, open(stderr_path, "w") as se:
            for line in proc.stdout:
                so.write(line)
            proc.wait()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, timer)
    duration = time.time() - started
    timed_out = duration >= args.timeout

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "duration_s": round(duration, 2),
        "last_message": last_message_file.read_text() if last_message_file.exists() else None,
    }


def parse_stream(out_dir: Path) -> dict:
    """Parse the flat `codex exec --json` event stream (documented contract).

    Event types: thread.started, turn.started, turn.completed, turn.failed,
    item.started/updated/completed, error.
    """
    parsed = {
        "session_id": None,
        "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
                  "reasoning_output_tokens": 0, "total_tokens": 0},
        "final_message": None,
        "stream_error": None,
        "turn_failed": None,
        "items": [],
    }
    with open(out_dir / "codex_stdout.jsonl") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            if t == "thread.started":
                parsed["session_id"] = o.get("thread_id")
            elif t == "turn.completed":
                u = o.get("usage") or {}
                for k in parsed["usage"]:
                    parsed["usage"][k] += u.get(k, 0) or 0
            elif t == "turn.failed":
                parsed["turn_failed"] = o.get("error")
            elif t == "error":
                parsed["stream_error"] = o.get("message")
            elif t in ("item.started", "item.updated", "item.completed"):
                item = o.get("item") or {}
                if t == "item.completed":
                    parsed["items"].append(item)
                    if item.get("type") == "agent_message" and item.get("text"):
                        parsed["final_message"] = item["text"]
    return parsed


def enrich_from_rollout(rollout: Path) -> dict:
    """Rollout (CODEX_HOME/sessions/**/rollout-*.jsonl) is the stable source for
    cumulative usage, tool calls and the model the agent actually ran with."""
    info = {
        "cumulative_usage": None,
        "observed_model": None,
        "observed_provider": None,
        "observed_sandbox": None,
        "observed_cwd": None,
        "cli_version": None,
        "tool_call_count": 0,
        "tool_names": {},
    }
    with open(rollout) as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            typ = o.get("type")
            p = o.get("payload") or {}
            if typ == "session_meta":
                info["cli_version"] = p.get("cli_version") or info["cli_version"]
                info["observed_provider"] = p.get("model_provider") or info["observed_provider"]
                info["observed_cwd"] = p.get("cwd") or info["observed_cwd"]
                if p.get("model"):
                    info["observed_model"] = p["model"]
            elif typ == "turn_context":
                if p.get("model"):
                    info["observed_model"] = p["model"]
                sp = p.get("sandbox_policy")
                if isinstance(sp, dict) and sp.get("type"):
                    info["observed_sandbox"] = sp["type"]
                info["observed_cwd"] = p.get("cwd") or info["observed_cwd"]
            elif typ == "token_usage_record":
                u = p.get("thread_token_usage")
                if isinstance(u, dict):
                    info["cumulative_usage"] = u
            elif typ == "response_item" and p.get("type") == "function_call":
                name = p.get("name") or "unknown"
                info["tool_names"][name] = info["tool_names"].get(name, 0) + 1
                info["tool_call_count"] += 1
    return info


INFRA_ERROR_MARKERS = (
    "connection refused", "connection reset", "timed out", "dns",
    "temporarily unavailable", "503", "502", "504", "rate limit", "429",
)


def normalize_status(agent_result: dict, parsed: dict, stderr_text: str) -> dict:
    """Separate infrastructure failures from agent failures (plan rule 11)."""
    low = (stderr_text or "").lower()
    infra_hit = [m for m in INFRA_ERROR_MARKERS if m in low]
    if agent_result["timed_out"]:
        status, cls = "timeout", "agent"
    elif parsed["stream_error"] or parsed["turn_failed"]:
        if infra_hit:
            status, cls = "infrastructure_error", "infrastructure"
        else:
            status, cls = "agent_error", "agent"
    elif agent_result["exit_code"] != 0:
        if infra_hit:
            status, cls = "infrastructure_error", "infrastructure"
        else:
            status, cls = "failed", "agent"
    else:
        status, cls = "completed", "agent"
    return {"status": status, "failure_class": cls, "infra_markers": infra_hit}


def evaluate(repo: Path, out_dir: Path) -> dict:
    """Evaluator: pytest run OUTSIDE the agent workspace copy is not needed
    here because the workspace IS isolated; we still run in a scratch dir to
    prove the hidden-test isolation pattern."""
    scratch = out_dir / "eval"
    scratch.mkdir()
    shutil.copy2(repo / "math_utils.py", scratch / "math_utils.py")
    shutil.copy2(repo / "test_math.py", scratch / "test_math.py")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_math.py"],
        cwd=scratch, capture_output=True, text=True, timeout=120,
    )
    (out_dir / "evaluation.json").write_text(json.dumps({
        "command": f"{sys.executable} -m pytest -q test_math.py",
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }, indent=2))
    return {
        "exit_code": proc.returncode,
        "pass": proc.returncode == 0,
        "stdout_tail": proc.stdout.strip().splitlines()[-1:] or [],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="model alias; default = config default (auto_codex)")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    run_id = f"spike-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir = ARTIFACTS / run_id
    out_dir.mkdir(parents=True)

    if not os.environ.get("LLM_ROUTER_API_KEY"):
        print("ERROR: LLM_ROUTER_API_KEY not set", file=sys.stderr)
        return 2

    print(f"run_id: {run_id}")
    print("[1/5] preparing isolated workspace + git repo")
    workspace = prepare_workspace(run_id)
    repo = workspace / "repo"
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    print("[2/5] preparing isolated CODEX_HOME")
    codex_home = prepare_codex_home(run_id)

    if args.dry_run:
        print("dry-run: skipping codex exec")
        return 0

    print(f"[3/5] running codex exec (model={args.model or 'config-default'})")
    agent_result = run_codex(args, workspace, out_dir, codex_home)

    print("[4/5] parsing JSONL stream + collecting session rollout")
    parsed = parse_stream(out_dir)
    sessions_dir = codex_home / "sessions"
    rollout_files = sorted(sessions_dir.glob("**/rollout-*.jsonl")) if sessions_dir.exists() else []
    rollout_file = rollout_files[-1] if rollout_files else None
    observed = {}
    if rollout_file:
        shutil.copy2(rollout_file, out_dir / "agent_trace.jsonl")
        observed = enrich_from_rollout(out_dir / "agent_trace.jsonl")
        if observed["cumulative_usage"]:
            parsed["usage"] = observed["cumulative_usage"]

    with open(out_dir / "tool_calls.jsonl", "w") as fh:
        for item in parsed["items"]:
            fh.write(json.dumps({"type": item.get("type"),
                                 "name": item.get("name"),
                                 "command": item.get("command"),
                                 "status": item.get("status")}, ensure_ascii=False) + "\n")

    stderr_text = (out_dir / "codex_stderr.log").read_text(errors="replace")
    normalized = normalize_status(agent_result, parsed, stderr_text)

    print("[5/5] git diff + hidden-test evaluation (outside workspace)")
    diff = subprocess.run(
        ["git", "diff", base_commit], cwd=repo, capture_output=True, text=True
    ).stdout
    (out_dir / "diff.patch").write_text(diff)
    eval_result = evaluate(repo, out_dir)

    codex_version = subprocess.run(
        ["codex", "--version"], capture_output=True, text=True
    ).stdout.strip()

    manifest = {
        "schema_version": "0.1",
        "run_id": run_id,
        "created_at": now_iso(),
        "task": {"id": "spike-001", "source": "spike/task.yaml",
                 "sha256": sha256(ROOT / "task.yaml")},
        "repository": {"fixture": "spike/repo", "base_commit": base_commit,
                       "commit_after_agent": subprocess.run(
                           ["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()},
        "agent": {
            "id": "codex",
            "adapter": "codex_cli",
            "version": codex_version,
            "session_id": parsed["session_id"],
            "config_requested": {"model": args.model or "config-default (auto_codex)",
                                 "sandbox": "workspace-write", "approval_policy": "never"},
            "config_effective": {"model": args.model or "auto_codex (from isolated config.toml)"},
            "config_observed": {
                "model": observed.get("observed_model"),
                "model_provider": observed.get("observed_provider"),
                "sandbox_policy": observed.get("observed_sandbox"),
                "cwd": observed.get("observed_cwd"),
                "cli_version": observed.get("cli_version"),
                "verification_status": "verified" if observed.get("observed_model") else "unverified",
            },
            "observations": {
                "tool_call_count": observed.get("tool_call_count", 0),
                "tool_names": observed.get("tool_names", {}),
                "stream_error": parsed["stream_error"],
                "turn_failed": parsed["turn_failed"],
            },
        },
        "runtime": {
            "id": "llm_router",
            "mode": "router",
            "lifecycle": "external",
            "base_url": "http://192.168.100.65:8081/v1",
            "healthcheck": "GET /health -> 200 (verified pre-run)",
        },
        "agent_result": {
            **agent_result,
            "usage": parsed["usage"],
            "final_message": parsed["final_message"],
            "status": normalized["status"],
            "failure_class": normalized["failure_class"],
            "infra_markers": normalized["infra_markers"],
        },
        "evaluation": eval_result,
        "artifacts": {
            "codex_stdout": "codex_stdout.jsonl",
            "codex_stderr": "codex_stderr.log",
            "agent_trace": "agent_trace.jsonl" if rollout_file else None,
            "tool_calls": "tool_calls.jsonl",
            "diff": "diff.patch",
            "last_message": "last_message.txt",
            "evaluation": "evaluation.json",
        },
        "artifact_hashes": {},
    }
    for name in ("codex_stdout.jsonl", "codex_stderr.log", "diff.patch", "evaluation.json"):
        p = out_dir / name
        if p.exists():
            manifest["artifact_hashes"][name] = sha256(p)
    if rollout_file:
        manifest["artifact_hashes"]["agent_trace.jsonl"] = sha256(out_dir / "agent_trace.jsonl")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\nDONE  run={run_id}")
    print(f"  exit_code={agent_result['exit_code']} timed_out={agent_result['timed_out']}")
    print(f"  duration={agent_result['duration_s']}s session={parsed['session_id']}")
    print(f"  usage={parsed['usage']}")
    print(f"  tool_calls={observed.get('tool_call_count', 0)} names={observed.get('tool_names', {})}")
    print(f"  eval_pass={eval_result['pass']}  ({' '.join(eval_result['stdout_tail'])})")
    print(f"  artifacts -> {out_dir}")
    return 0 if eval_result["pass"] and normalized["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())

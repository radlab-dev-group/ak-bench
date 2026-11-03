"""Packaging of workspace solutions, traces, and evaluation results (auditability & reproducibility)."""

from __future__ import annotations

import fnmatch
import os
import subprocess
import zipfile
from pathlib import Path

EXCLUDED_DIR_NAMES: set[str] = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".tox",
    ".idea",
    ".vscode",
}

EXCLUDED_FILE_PATTERNS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    ".git",
)

TRACE_FILENAMES: tuple[str, ...] = (
    "agent_stdout.jsonl",
    "agent_stderr.log",
    # The log of a runtime AK-Bench started for this run: the router's own
    # account of the requests, the routing decision and the plugin behaviour.
    "router.log",
    "last_message.txt",
    "agent_trace.jsonl",
    "tool_calls.jsonl",
    "runtime_trace.jsonl",
    "events.jsonl",
    "stdout.log",
    "stderr.log",
)


def _is_excluded_file(filename: str) -> bool:
    return any(fnmatch.fnmatch(filename, pat) for pat in EXCLUDED_FILE_PATTERNS)


def pack_solution_diff(workspace_dir: Path | str, output_patch: Path | str) -> Path | None:
    """Generate git diff representing all changes made by the agent in workspace."""
    workspace = Path(workspace_dir)
    if not workspace.is_dir():
        return None
    out = Path(output_patch)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Include untracked files in diff via intent-to-add if git repository
        subprocess.run(
            ["git", "add", "-N", "."],
            cwd=str(workspace),
            capture_output=True,
            timeout=15,
            check=False,
        )
        res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        diff_text = res.stdout
        if not diff_text and res.returncode != 0:
            res = subprocess.run(
                ["git", "diff"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            diff_text = res.stdout
        out.write_text(diff_text or "", encoding="utf-8")
        return out
    except Exception:
        return None


def pack_solution_workspace(workspace_dir: Path | str, output_zip: Path | str) -> Path | None:
    """Create a zip archive of clean workspace files (excluding caches/git/venv)."""
    workspace = Path(workspace_dir)
    if not workspace.is_dir():
        return None
    out = Path(output_zip)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(workspace):
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES]
                for file in files:
                    if _is_excluded_file(file):
                        continue
                    full_path = Path(root) / file
                    arcname = full_path.relative_to(workspace)
                    zf.write(full_path, arcname=str(arcname))
        return out
    except Exception:
        return None


def pack_agent_traces(artifacts_dir: Path | str, output_zip: Path | str) -> Path | None:
    """Create a zip archive of agent traces and logs found in artifacts_dir."""
    artifacts = Path(artifacts_dir)
    if not artifacts.is_dir():
        return None
    out = Path(output_zip)
    out.parent.mkdir(parents=True, exist_ok=True)
    candidates = [artifacts / name for name in TRACE_FILENAMES if (artifacts / name).is_file()]
    if not candidates:
        return None
    try:
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file in candidates:
                zf.write(file, arcname=file.name)
        return out
    except Exception:
        return None


def pack_evaluation_results(evaluation_dir: Path | str, output_zip: Path | str) -> Path | None:
    """Create a zip archive of evaluation output directory."""
    eval_dir = Path(evaluation_dir)
    if not eval_dir.is_dir():
        return None
    out = Path(output_zip)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        files_to_pack = [p for p in eval_dir.rglob("*") if p.is_file()]
        if not files_to_pack:
            return None
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file in files_to_pack:
                arcname = file.relative_to(eval_dir)
                zf.write(file, arcname=str(arcname))
        return out
    except Exception:
        return None


def collect_and_package_artifacts(
    workspace_dir: Path | str | None,
    artifacts_dir: Path | str | None,
    evaluation_dir: Path | str | None = None,
) -> list[Path]:
    """Collect and package all solution, trace and evaluation archives into artifacts_dir."""
    if not artifacts_dir:
        return []
    artifacts = Path(artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    if workspace_dir and Path(workspace_dir).is_dir():
        patch_file = pack_solution_diff(workspace_dir, artifacts / "diff.patch")
        if patch_file:
            created.append(patch_file)
        sol_zip = pack_solution_workspace(workspace_dir, artifacts / "solution.zip")
        if sol_zip:
            created.append(sol_zip)

    traces_zip = pack_agent_traces(artifacts, artifacts / "agent_traces.zip")
    if traces_zip:
        created.append(traces_zip)

    eval_target = evaluation_dir or (artifacts / "evaluation")
    if eval_target and Path(eval_target).is_dir():
        eval_zip = pack_evaluation_results(eval_target, artifacts / "evaluation.zip")
        if eval_zip:
            created.append(eval_zip)

    return created

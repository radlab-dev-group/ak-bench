"""The static analysis evaluator (plan section 16, supplementary).

A static analyser is a signal, not a verdict: the descriptor says so, and this
implementation follows it. It runs the analyser the task declares — `ruff` by
default — over an isolated copy of the produced workspace, parses its findings,
and reports them as a score.

The outcome vocabulary:

- the analyser ran and found nothing → `passed`;
- the analyser ran and found something → `partial`, or `failed` when nothing it
  looked at came out clean (a finding is a reason to look, not proof the task
  is unsolved, so it can never be the only evidence a task failed either);
- the analyser itself broke (bad invocation, unreadable output) →
  `evaluator_error`;
- the analyser is not installed → `infrastructure_error`, never a zero score.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from akbench.evaluators.engine import EvaluationResult, EvaluationVerdict
from akbench.evaluators.isolation import evaluation_sandbox

EVALUATOR_ID = "static_analysis_evaluator"
EVALUATOR_VERSION = "1.0.0"

#: The analyser to run when the task declares none: ruff, with a machine report.
DEFAULT_COMMAND = [sys.executable, "-m", "ruff", "check", "--output-format=json", "."]

#: Exit codes as ruff documents them; anything else is an unusable report.
ANALYSER_CLEAN = 0
ANALYSER_FINDINGS = 1
ANALYSER_MISUSE = 2


class StaticAnalysisEvaluator:
    """Runs a static analyser over a copy of the workspace and scores its findings."""

    evaluator_id = EVALUATOR_ID
    kind = "static_analysis"

    def evaluate(
        self,
        workspace: Path,
        *,
        out_dir: Path,
        timeout: float | None = None,
        command: str | list[str] | None = None,
        pythonpath: list[str] | None = None,
        **inputs: Any,
    ) -> EvaluationResult:
        started = time.time()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        argv = _argv(command) or list(DEFAULT_COMMAND)
        with evaluation_sandbox(Path(workspace)) as sandbox:
            env = dict(os.environ)
            search = [str(sandbox), str(sandbox / "src")]
            search.extend(str(sandbox / entry) for entry in pythonpath or [])
            if env.get("PYTHONPATH"):
                search.append(env["PYTHONPATH"])
            env["PYTHONPATH"] = os.pathsep.join(search)
            try:
                completed = subprocess.run(  # fixed argv, no shell
                    argv,
                    cwd=sandbox,
                    env=env,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return _result(
                    EvaluationVerdict.TIMEOUT,
                    details={"timeout_seconds": timeout, "command": argv},
                    started=started,
                )
            except (OSError, ValueError) as exc:
                return _result(
                    EvaluationVerdict.EVALUATOR_ERROR,
                    details={"reason": f"the analyser could not run: {exc}", "command": argv},
                    started=started,
                )

        raw = _raw(completed)
        raw_path = out_dir / "static-analysis.txt"
        raw_path.write_text(raw, encoding="utf-8")

        stderr = (completed.stderr or "").strip()
        if _is_missing_module(stderr):
            # The analyser is not installed: the environment could not run the
            # measurement, which is neither a pass nor a zero for the agent.
            return _result(
                EvaluationVerdict.INFRASTRUCTURE_ERROR,
                details={"reason": stderr, "command": argv, "exit_code": completed.returncode},
                raw=_raw(completed),
                started=started,
            )
        if completed.returncode >= ANALYSER_MISUSE and not (completed.stdout or "").strip():
            reason = stderr or "the analyser reported nothing usable"
            verdict = EvaluationVerdict.EVALUATOR_ERROR
            return _result(
                verdict,
                details={"reason": reason, "command": argv, "exit_code": completed.returncode},
                raw=raw,
                started=started,
                artifacts={"report": str(raw_path)},
            )

        findings = _findings(completed.stdout or "")
        if findings is None:
            return _result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={
                    "reason": "the analyser produced a report this evaluator cannot read",
                    "command": argv,
                    "exit_code": completed.returncode,
                },
                raw=raw,
                started=started,
                artifacts={"report": str(raw_path)},
            )

        # The analyser reports what it disliked, never what it scanned, so the
        # score is binary (clean or not) and a finding is `partial`: a reason to
        # look, never proof that the task is unsolved (the descriptor says so).
        analysed = sorted({str(item.get("filename") or "?") for item in findings})
        score = 1.0 if not findings else 0.0
        verdict = EvaluationVerdict.PASSED if not findings else EvaluationVerdict.PARTIAL
        codes: dict[str, int] = {}
        for item in findings:
            code = str(item.get("code") or "unknown")
            codes[code] = codes.get(code, 0) + 1

        return _result(
            verdict,
            score=score,
            passed=0 if findings else 1,
            failed=1 if findings else 0,
            total=1,
            details={
                "command": argv,
                "exit_code": completed.returncode,
                "findings": len(findings),
                "files_with_findings": analysed,
                "codes": codes,
                "note": "static analysis is supplementary; hidden tests decide correctness",
            },
            raw=raw,
            started=started,
            artifacts={"report": str(raw_path)},
        )


def _argv(command: str | list[str] | None) -> list[str] | None:
    if not command:
        return None
    if isinstance(command, list):
        return [str(part) for part in command if str(part)]
    try:
        return shlex.split(command)
    except ValueError:
        return None


def _findings(stdout: str) -> list[dict[str, Any]] | None:
    """Parse a ruff JSON report; fall back to counting `path:line:col:` lines."""
    text = stdout.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _text_findings(text)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return _text_findings(text)


def _text_findings(text: str) -> list[dict[str, Any]]:
    """A line the analyser located is a finding; anything else is prose."""
    findings: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split(":", 3)
        if len(parts) >= 4 and parts[1].isdigit() and parts[2].isdigit():
            findings.append({"filename": parts[0], "code": "text"})
    return findings


def _raw(completed: subprocess.CompletedProcess) -> str:
    return (
        f"--- stdout ---\n{completed.stdout or ''}\n"
        f"--- stderr ---\n{completed.stderr or ''}\n"
    )


def _is_missing_module(stderr: str) -> bool:
    return "No module named" in stderr or "not found" in stderr.lower()


def _result(
    verdict: EvaluationVerdict,
    *,
    score: float | None = None,
    passed: int | None = None,
    failed: int | None = None,
    total: int | None = None,
    details: dict[str, Any] | None = None,
    raw: str | None = None,
    started: float,
    artifacts: dict[str, str] | None = None,
) -> EvaluationResult:
    return EvaluationResult(
        evaluator_id=EVALUATOR_ID,
        evaluator_version=EVALUATOR_VERSION,
        verdict=verdict,
        score=score,
        passed=passed,
        failed=failed,
        total=total,
        duration_seconds=round(time.time() - started, 3),
        details=dict(details or {}),
        raw=raw,
        artifacts=dict(artifacts or {}),
    )

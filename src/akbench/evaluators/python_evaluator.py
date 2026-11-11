"""The custom Python evaluator (plan section 16).

A task may judge itself with Python: the evaluator runs a script the task ships
in a **separate process** and reads back a JSON verdict.

The contract has three rules, and each exists to keep a custom evaluator from
becoming a way to fake a result:

1. The script runs against an isolated copy of the produced workspace and gets
   that copy's path, never the agent's, so it cannot rewrite what it judges.
2. It reports through a JSON file in ``--out-dir``. A script that raises, exits
   non-zero or writes nothing is an `evaluator_error`, never a pass and never a
   zero attributed to the agent.
3. Only the verdict vocabulary of plan 16 is accepted. A script cannot invent
   an outcome the reports do not know.

The script runs as a subprocess of the benchmark process, with its privileges:
this is a host sandbox, not a security boundary. Docker isolation (deferred,
see ``docs/ISOLATION_AND_SECURITY.md``) is what would change that; until then a
task must ship only a script its operator would run by hand.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from akbench.evaluators.engine import EvaluationResult, EvaluationVerdict
from akbench.evaluators.isolation import evaluation_sandbox

EVALUATOR_ID = "python_evaluator"
EVALUATOR_VERSION = "1.0.0"

#: The file a custom evaluator writes its verdict into, inside ``--out-dir``.
RESULT_NAME = "evaluator-result.json"

#: A custom evaluator may report any outcome except blaming infrastructure:
#: that verdict belongs to this evaluator, not to a script it cannot verify.
REPORTABLE = {
    EvaluationVerdict.PASSED,
    EvaluationVerdict.PARTIAL,
    EvaluationVerdict.FAILED,
    EvaluationVerdict.REGRESSION,
    EvaluationVerdict.EVALUATOR_ERROR,
}


def _result(
    verdict: EvaluationVerdict,
    *,
    score: float | None = None,
    passed: int | None = None,
    failed: int | None = None,
    skipped: int | None = None,
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
        skipped=skipped,
        total=total,
        duration_seconds=round(time.time() - started, 3),
        details=dict(details or {}),
        raw=raw,
        artifacts=dict(artifacts or {}),
    )


def _count(payload: dict[str, Any], name: str) -> int | None:
    value = payload.get(name)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class PythonEvaluator:
    """Runs a task-provided Python evaluator as a subprocess and reads its verdict."""

    evaluator_id = EVALUATOR_ID
    kind = "python"

    def evaluate(
        self,
        workspace: Path,
        *,
        out_dir: Path,
        timeout: float | None = None,
        script: str | Path | None = None,
        pythonpath: list[str] | None = None,
        python_executable: str | None = None,
        **inputs: Any,
    ) -> EvaluationResult:
        started = time.time()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if not script:
            return _result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={"reason": "the task declares no evaluator script"},
                started=started,
            )
        script_path = Path(script)
        if not script_path.is_file():
            return _result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={"reason": f"evaluator script not found: {script_path}"},
                started=started,
            )

        interpreter = python_executable or sys.executable
        result_file = out_dir / RESULT_NAME
        if result_file.exists():
            result_file.unlink()

        with evaluation_sandbox(Path(workspace)) as sandbox:
            env = dict(os.environ)
            search = [str(sandbox), str(sandbox / "src")]
            search.extend(str(sandbox / entry) for entry in pythonpath or [])
            if env.get("PYTHONPATH"):
                search.append(env["PYTHONPATH"])
            env["PYTHONPATH"] = os.pathsep.join(search)
            argv = [
                interpreter,
                str(script_path),
                "--workspace",
                str(sandbox),
                "--out-dir",
                str(out_dir),
            ]
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
                    details={"timeout_seconds": timeout, "script": str(script_path)},
                    started=started,
                )
            except (OSError, ValueError) as exc:
                return _result(
                    EvaluationVerdict.EVALUATOR_ERROR,
                    details={"reason": f"the evaluator script could not run: {exc}"},
                    started=started,
                )

        raw = (
            f"--- stdout ---\n{completed.stdout or ''}\n"
            f"--- stderr ---\n{completed.stderr or ''}\n"
        )
        raw_path = out_dir / "python-evaluator-output.txt"
        raw_path.write_text(raw, encoding="utf-8")
        artifacts = {"output": str(raw_path)}

        if not result_file.is_file():
            return _result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={
                    "reason": f"the script exited ({completed.returncode}) without writing "
                    f"{RESULT_NAME} in --out-dir",
                    "exit_code": completed.returncode,
                },
                raw=raw,
                started=started,
                artifacts=artifacts,
            )
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={"reason": f"{RESULT_NAME} is not readable JSON: {exc}"},
                raw=raw,
                started=started,
                artifacts=artifacts,
            )
        if not isinstance(payload, dict):
            return _result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={"reason": f"{RESULT_NAME} must hold a JSON object"},
                raw=raw,
                started=started,
                artifacts=artifacts,
            )
        try:
            verdict = EvaluationVerdict(str(payload.get("verdict", "")))
        except ValueError:
            return _result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={
                    "reason": f"the script reported an unknown verdict: {payload.get('verdict')!r}",
                    "accepted": sorted(item.value for item in REPORTABLE),
                },
                raw=raw,
                started=started,
                artifacts=artifacts,
            )
        if verdict not in REPORTABLE:
            return _result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={
                    "reason": f"a script may not report {verdict.value}; "
                    "infrastructure errors belong to the evaluator",
                    "accepted": sorted(item.value for item in REPORTABLE),
                },
                raw=raw,
                started=started,
                artifacts=artifacts,
            )

        score = payload.get("score")
        details = payload.get("details")
        return _result(
            verdict,
            score=float(score)
            if isinstance(score, (int, float)) and not isinstance(score, bool)
            else None,
            passed=_count(payload, "passed"),
            failed=_count(payload, "failed"),
            skipped=_count(payload, "skipped"),
            total=_count(payload, "total"),
            details=dict(details) if isinstance(details, dict) else {},
            raw=raw,
            started=started,
            artifacts={**artifacts, RESULT_NAME: str(result_file)},
        )

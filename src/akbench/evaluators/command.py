"""The command evaluator — the generic escape hatch of plan section 16.

Any command that exits ``0`` on success can judge a task. The same rules as the
pytest evaluator apply: the command runs in an isolated copy of the produced
workspace (never in the agent's workspace), its raw output is kept, and the
three failure kinds stay separate:

- non-zero exit → the agent did not satisfy the task;
- timeout → its own verdict;
- the command could not be executed at all → an evaluator error, because the
  measurement failed rather than the agent.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from akbench.evaluators.engine import EvaluationResult, EvaluationVerdict
from akbench.evaluators.isolation import evaluation_sandbox

EVALUATOR_ID = "command_evaluator"
EVALUATOR_VERSION = "1.0.0"


class CommandEvaluator:
    """Runs one declared command against a copy of the produced workspace."""

    evaluator_id = EVALUATOR_ID
    kind = "command"

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

        argv = _argv(command)
        if argv is None:
            return EvaluationResult(
                evaluator_id=self.evaluator_id,
                evaluator_version=EVALUATOR_VERSION,
                verdict=EvaluationVerdict.EVALUATOR_ERROR,
                details={"reason": "the task declares no evaluator command"},
            )

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
                return EvaluationResult(
                    evaluator_id=self.evaluator_id,
                    evaluator_version=EVALUATOR_VERSION,
                    verdict=EvaluationVerdict.TIMEOUT,
                    duration_seconds=round(time.time() - started, 3),
                    details={"timeout_seconds": timeout, "command": argv},
                )
            except (OSError, ValueError) as exc:
                return EvaluationResult(
                    evaluator_id=self.evaluator_id,
                    evaluator_version=EVALUATOR_VERSION,
                    verdict=EvaluationVerdict.EVALUATOR_ERROR,
                    duration_seconds=round(time.time() - started, 3),
                    details={"reason": f"the evaluator command could not run: {exc}"},
                )

        raw = (
            f"--- stdout ---\n{completed.stdout or ''}\n"
            f"--- stderr ---\n{completed.stderr or ''}\n"
        )
        raw_path = out_dir / "command-output.txt"
        raw_path.write_text(raw, encoding="utf-8")

        passed = completed.returncode == 0
        return EvaluationResult(
            evaluator_id=self.evaluator_id,
            evaluator_version=EVALUATOR_VERSION,
            verdict=EvaluationVerdict.PASSED if passed else EvaluationVerdict.FAILED,
            score=1.0 if passed else 0.0,
            passed=1 if passed else 0,
            failed=0 if passed else 1,
            total=1,
            duration_seconds=round(time.time() - started, 3),
            details={
                "command": argv,
                "exit_code": completed.returncode,
                "cwd": str(sandbox),
            },
            raw=raw,
            artifacts={"output": str(raw_path)},
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

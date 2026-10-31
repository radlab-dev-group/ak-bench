"""Mutation verification (plan section 8.4).

A bug-fix task is only real if its defect is proven: the hidden tests must pass
on the base commit and fail once the mutation is applied. Anything else means
the task is broken or the defect is invisible, and shipping such a task would
turn a benchmark into noise.

Verification runs in its own throwaway workspaces, which are removed again; the
hidden tests are copied in for the duration of the run and deleted afterwards,
so they never persist inside a workspace an agent might later see.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from akbench.core.errors import WorkspaceError
from akbench.datasets.dataset import LoadedTask
from akbench.datasets.workspace import WorkspaceManager

HIDDEN_TESTS_DIRNAME = ".akbench_hidden_tests"


class MutationVerdict(StrEnum):
    """Outcome of verifying a task's mutation."""

    VERIFIED = "verified"
    NO_MUTATION = "no_mutation"
    BASE_BROKEN = "base_broken"
    NOT_DETECTABLE = "not_detectable"
    TEST_ERROR = "test_error"


@dataclass(frozen=True)
class TestRun:
    """Result of running the hidden tests once."""

    exit_code: int
    passed: bool | None
    output: str = ""

    @property
    def errored(self) -> bool:
        """True when pytest could not run or collect, as opposed to failing."""
        return self.passed is None


@dataclass(frozen=True)
class MutationVerification:
    task_uid: str
    verdict: MutationVerdict
    base: TestRun | None = None
    mutated: TestRun | None = None
    details: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict in (MutationVerdict.VERIFIED, MutationVerdict.NO_MUTATION)

    def as_dict(self) -> dict[str, object]:
        def run_payload(run: TestRun | None) -> dict[str, object] | None:
            if run is None:
                return None
            return {"exit_code": run.exit_code, "passed": run.passed}

        return {
            "task": self.task_uid,
            "verdict": self.verdict.value,
            "ok": self.ok,
            "base": run_payload(self.base),
            "mutated": run_payload(self.mutated),
            "details": self.details,
        }


def run_hidden_tests(
    workspace: Path,
    hidden_tests: Path,
    *,
    timeout_seconds: int = 300,
    python_executable: str | None = None,
) -> TestRun:
    """Run the hidden tests against a workspace copy.

    The tests are copied into the workspace so that imports resolve relative to
    the code under test, and the copy is removed afterwards. A pytest exit code
    of 5 (no tests collected) is treated as an error, never as a pass.
    """
    workspace = Path(workspace)
    hidden_tests = Path(hidden_tests)
    if not hidden_tests.is_dir():
        raise WorkspaceError(f"hidden tests directory not found: {hidden_tests}")

    staging = Path(tempfile.mkdtemp(prefix=HIDDEN_TESTS_DIRNAME, dir=str(workspace)))
    target = staging / hidden_tests.name
    # The tests live outside the repository, so the code under test is put on
    # the path explicitly: the workspace root and its conventional ``src``.
    child_env = {**os.environ}
    existing = child_env.get("PYTHONPATH")
    search = [str(workspace), str(workspace / "src")] + ([existing] if existing else [])
    child_env["PYTHONPATH"] = os.pathsep.join(search)
    try:
        shutil.copytree(hidden_tests, target)
        completed = subprocess.run(  # fixed argv, no shell
            [
                python_executable or sys.executable,
                "-m",
                "pytest",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                str(target),
            ],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=child_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError(f"hidden tests timed out after {timeout_seconds}s") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return TestRun(exit_code=0, passed=True, output=output)
    if completed.returncode == 1:
        return TestRun(exit_code=1, passed=False, output=output)
    return TestRun(exit_code=completed.returncode, passed=None, output=output)


class MutationVerifier:
    """Proves a task's mutation: hidden tests pass on base, fail when mutated."""

    def __init__(
        self,
        workspaces: WorkspaceManager,
        *,
        timeout_seconds: int = 300,
        python_executable: str | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.timeout_seconds = timeout_seconds
        self.python_executable = python_executable

    def verify(self, loaded: LoadedTask, task_dir: Path | None = None) -> MutationVerification:
        task = loaded.task
        directory = Path(task_dir) if task_dir is not None else loaded.path
        hidden = directory / task.task.hidden_tests

        if task.task.mutation is None:
            return MutationVerification(
                task_uid=loaded.uid,
                verdict=MutationVerdict.NO_MUTATION,
                details={"reason": "task declares no mutation; nothing to verify"},
            )

        nonce = uuid.uuid4().hex[:8]
        base_run: TestRun | None = None
        mutated_run: TestRun | None = None

        base_workspace = self.workspaces.prepare(
            task, f"verify-{nonce}-base", task_dir=directory, apply_mutation=False
        )
        try:
            base_run = run_hidden_tests(
                base_workspace.path, hidden, timeout_seconds=self.timeout_seconds,
                python_executable=self.python_executable,
            )
        finally:
            self.workspaces.cleanup(base_workspace.path)

        if base_run.errored:
            return MutationVerification(
                task_uid=loaded.uid,
                verdict=MutationVerdict.TEST_ERROR,
                base=base_run,
                details={"stage": "base", "output": _tail(base_run.output)},
            )
        if not base_run.passed:
            return MutationVerification(
                task_uid=loaded.uid,
                verdict=MutationVerdict.BASE_BROKEN,
                base=base_run,
                details={
                    "stage": "base",
                    "output": _tail(base_run.output),
                    "hint": "the task's own tests do not pass on the pinned base commit",
                },
            )

        mutated_workspace = self.workspaces.prepare(
            task, f"verify-{nonce}-mutated", task_dir=directory, apply_mutation=True
        )
        try:
            mutated_run = run_hidden_tests(
                mutated_workspace.path, hidden, timeout_seconds=self.timeout_seconds,
                python_executable=self.python_executable,
            )
        finally:
            self.workspaces.cleanup(mutated_workspace.path)

        if mutated_run.errored:
            return MutationVerification(
                task_uid=loaded.uid,
                verdict=MutationVerdict.TEST_ERROR,
                base=base_run,
                mutated=mutated_run,
                details={"stage": "mutated", "output": _tail(mutated_run.output)},
            )
        if mutated_run.passed:
            return MutationVerification(
                task_uid=loaded.uid,
                verdict=MutationVerdict.NOT_DETECTABLE,
                base=base_run,
                mutated=mutated_run,
                details={
                    "hint": "hidden tests pass with the defect applied, "
                    "so the mutation is invisible"
                },
            )

        return MutationVerification(
            task_uid=loaded.uid,
            verdict=MutationVerdict.VERIFIED,
            base=base_run,
            mutated=mutated_run,
        )


def _tail(output: str, lines: int = 12) -> str:
    stripped = output.strip().splitlines()
    return "\n".join(stripped[-lines:])

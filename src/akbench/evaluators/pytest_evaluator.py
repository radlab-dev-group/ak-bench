"""The pytest evaluator — the primary evaluator of plan section 16.

Design decisions that follow from the plan:

- hidden tests run in an isolated **copy** of the produced workspace, never in
  the agent's workspace, so the agent can neither read nor modify them and
  evaluation cannot change what was produced (plan 8.6, 23);
- raw results are kept (the JUnit XML report and the verbatim output) together
  with the evaluator version, so a verdict can always be re-examined;
- the outcome vocabulary distinguishes what pytest means by each exit code:
  ``5`` (no tests collected) and usage/internal errors are **evaluator errors**,
  never a pass and never an agent failure (plan rule 11);
- a timeout is its own verdict, and a missing pytest is an infrastructure
  problem, not a zero score.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from akbench.evaluators.engine import EvaluationResult, EvaluationVerdict
from akbench.evaluators.isolation import evaluation_sandbox

EVALUATOR_ID = "pytest_evaluator"
EVALUATOR_VERSION = "1.0.0"

PYTEST_OK = 0
PYTEST_TESTS_FAILED = 1
PYTEST_INTERRUPTED = 2
PYTEST_INTERNAL_ERROR = 3
PYTEST_USAGE_ERROR = 4
PYTEST_NO_TESTS = 5

#: Exit codes that mean the measurement itself broke (plan rule 11).
EVALUATOR_ERROR_CODES = {
    PYTEST_INTERRUPTED: "pytest was interrupted",
    PYTEST_INTERNAL_ERROR: "pytest reported an internal error",
    PYTEST_USAGE_ERROR: "pytest was invoked incorrectly",
    PYTEST_NO_TESTS: "pytest collected no tests",
}


@dataclass(frozen=True)
class TestCounts:
    """Counts and failing test names taken from a JUnit XML report.

    The names are what makes regression detection possible: a baseline records
    which tests passed before, and a previously passing test that now fails is
    a regression rather than a plain failure.
    """

    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    #: Identifiers as JUnit reports them (``classname`` without path separators).
    failing: frozenset[str] = frozenset()

    @property
    def score(self) -> float | None:
        scored = self.total - self.skipped
        if scored <= 0:
            return None
        return round(self.passed / scored, 6)


class PytestEvaluator:
    """Runs the task's hidden tests against a copy of the produced workspace."""

    evaluator_id = EVALUATOR_ID
    kind = "pytest"

    def evaluate(
        self,
        workspace: Path,
        *,
        out_dir: Path,
        timeout: float | None = None,
        hidden_tests: Path | None = None,
        pythonpath: list[str] | None = None,
        baseline: dict[str, str] | None = None,
        python_executable: str | None = None,
        **inputs: Any,
    ) -> EvaluationResult:
        workspace = Path(workspace)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if hidden_tests is None:
            return self._error(workspace, out_dir, "the task declares no hidden tests")
        if not Path(hidden_tests).is_dir():
            return self._error(
                workspace, out_dir, f"hidden tests directory not found: {hidden_tests}"
            )
        interpreter = python_executable or sys.executable
        if not self._pytest_available(interpreter):
            return self._infrastructure_error(workspace, out_dir, interpreter)

        started = time.time()
        with evaluation_sandbox(workspace, hidden_tests=hidden_tests) as sandbox:
            report = out_dir / "pytest-report.xml"
            command = [
                interpreter,
                "-m",
                "pytest",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                f"--junitxml={report}",
                "hidden_tests",
            ]
            completed = _run(command, sandbox, timeout, pythonpath)
            raw = _combine(completed)
            raw_path = out_dir / "pytest-output.txt"
            raw_path.write_text(raw, encoding="utf-8")
            duration = round(time.time() - started, 3)

            if completed is None:
                return EvaluationResult(
                    evaluator_id=self.evaluator_id,
                    evaluator_version=EVALUATOR_VERSION,
                    verdict=EvaluationVerdict.TIMEOUT,
                    duration_seconds=duration,
                    details={"timeout_seconds": timeout},
                    raw=raw,
                    artifacts={"output": str(raw_path)},
                )

            counts = _counts(report) if report.is_file() else None
            verdict = self._verdict(completed.returncode, counts, baseline)
            artifacts = {"output": str(raw_path)}
            if report.is_file():
                stored = out_dir / "junit.xml"
                stored.write_bytes(report.read_bytes())
                artifacts["junit_xml"] = str(stored)

            return EvaluationResult(
                evaluator_id=self.evaluator_id,
                evaluator_version=EVALUATOR_VERSION,
                verdict=verdict,
                score=counts.score if counts else None,
                passed=counts.passed if counts else None,
                failed=counts.failed + counts.errors if counts else None,
                skipped=counts.skipped if counts else None,
                total=counts.total if counts else None,
                duration_seconds=duration,
                details=self._details(completed.returncode, counts, baseline),
                raw=raw,
                artifacts=artifacts,
            )

    # -------------------------------------------------------------- verdicts

    def _verdict(
        self,
        exit_code: int,
        counts: TestCounts | None,
        baseline: dict[str, str] | None,
    ) -> EvaluationVerdict:
        if exit_code in EVALUATOR_ERROR_CODES:
            return EvaluationVerdict.EVALUATOR_ERROR
        if exit_code not in (PYTEST_OK, PYTEST_TESTS_FAILED):
            return EvaluationVerdict.EVALUATOR_ERROR
        if counts is None or counts.total == 0:
            return EvaluationVerdict.EVALUATOR_ERROR

        if exit_code == PYTEST_OK:
            return EvaluationVerdict.PASSED

        if _regressed(counts, baseline):
            return EvaluationVerdict.REGRESSION
        if counts.passed and counts.failed + counts.errors:
            return EvaluationVerdict.PARTIAL
        return EvaluationVerdict.FAILED

    def _details(
        self,
        exit_code: int,
        counts: TestCounts | None,
        baseline: dict[str, str] | None,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {"exit_code": exit_code}
        if counts:
            details.update(
                {
                    "total": counts.total,
                    "passed": counts.passed,
                    "failures": counts.failed,
                    "errors": counts.errors,
                    "skipped": counts.skipped,
                }
            )
        if exit_code in EVALUATOR_ERROR_CODES:
            details["reason"] = EVALUATOR_ERROR_CODES[exit_code]
        regressed = _regressed(counts, baseline)
        if regressed:
            details["regressed_tests"] = regressed
        return details

    def _error(self, workspace: Path, out_dir: Path, reason: str) -> EvaluationResult:
        return EvaluationResult(
            evaluator_id=self.evaluator_id,
            evaluator_version=EVALUATOR_VERSION,
            verdict=EvaluationVerdict.EVALUATOR_ERROR,
            details={"reason": reason, "workspace": str(workspace)},
        )

    def _infrastructure_error(
        self, workspace: Path, out_dir: Path, interpreter: str
    ) -> EvaluationResult:
        return EvaluationResult(
            evaluator_id=self.evaluator_id,
            evaluator_version=EVALUATOR_VERSION,
            verdict=EvaluationVerdict.INFRASTRUCTURE_ERROR,
            details={
                "reason": f"pytest is not available for {interpreter}",
                "workspace": str(workspace),
            },
        )

    @staticmethod
    def _pytest_available(interpreter: str) -> bool:
        try:
            completed = subprocess.run(
                [interpreter, "-c", "import pytest"],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0


def _run(
    command: list[str],
    cwd: Path,
    timeout: float | None,
    pythonpath: list[str] | None,
) -> subprocess.CompletedProcess | None:
    """Run pytest in the sandbox; ``None`` means it timed out."""
    env = dict(os.environ)
    search = [str(cwd), str(cwd / "src")]
    search.extend(str(cwd / entry) for entry in pythonpath or [])
    existing = env.get("PYTHONPATH")
    if existing:
        search.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(search)
    try:
        return subprocess.run(  # fixed argv, no shell
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None


def _combine(completed: subprocess.CompletedProcess) -> str:
    return f"--- stdout ---\n{completed.stdout or ''}\n--- stderr ---\n{completed.stderr or ''}\n"


def _counts(report: Path) -> TestCounts | None:
    """Read counts from the JUnit XML report (stdlib, no pytest plugin needed)."""
    try:
        root = ElementTree.parse(report).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return None

    def attribute(suite: ElementTree.Element, name: str) -> int:  # per-suite counters
        try:
            return int(suite.get(name, "0") or 0)
        except ValueError:
            return 0

    total = sum(attribute(suite, "tests") for suite in suites)
    failures = sum(attribute(suite, "failures") for suite in suites)
    errors = sum(attribute(suite, "errors") for suite in suites)
    skipped = sum(attribute(suite, "skipped") for suite in suites)
    passed = max(total - failures - errors - skipped, 0)
    return TestCounts(
        total=total,
        passed=passed,
        failed=failures,
        errors=errors,
        skipped=skipped,
        failing=_failing_names(root),
    )


def _failing_names(root: ElementTree.Element) -> frozenset[str]:
    """Identifiers of the test cases that did not pass, in JUnit form.

    The baseline and the report must use the same identifier shape, so the
    evaluator normalizes both sides through :func:`normalize_baseline`.
    """
    failing: set[str] = set()
    for case in root.iter("testcase"):
        if any(child.tag in ("failure", "error") for child in case):
            failing.add(_case_id(case))
    return frozenset(failing)


def _case_id(case: ElementTree.Element) -> str:
    name = case.get("name") or "unknown"
    classname = case.get("classname")
    return f"{classname}::{name}" if classname else name


def normalize_baseline(baseline: dict[str, str]) -> dict[str, str]:
    """Map baseline identifiers onto the JUnit shape the report uses.

    Accepts ``module.test`` (the pytest node form) and ``module::test``
    (the JUnit form) and rewrites dots inside the module to match how JUnit
    records the classname.
    """
    normalized: dict[str, str] = {}
    for identifier, outcome in baseline.items():
        if "::" in identifier:
            module, test = identifier.split("::", 1)
        else:
            module, _, test = identifier.rpartition(".")
            if not module:
                module, test = "", identifier
        normalized[f"{module}::{test}"] = outcome
    return normalized


def _regressed(counts: TestCounts | None, baseline: dict[str, str] | None) -> int:
    """How many previously passing tests now fail.

    The baseline maps a test identifier to its outcome on the base state. With
    no baseline a regression cannot be told apart from a plain failure, so the
    answer is 0 and the verdict stays ``partial``/``failed`` — never a guess.
    """
    if not baseline or counts is None:
        return 0
    normalized = normalize_baseline(baseline)
    passing_before = {key for key, outcome in normalized.items() if outcome == "passed"}
    if not passing_before:
        return 0
    return len(counts.failing & passing_before)

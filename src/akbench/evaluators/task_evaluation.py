"""Evaluating a task result (plan sections 8.6 and 16).

The task says which evaluator judges it and where its hidden tests live; this
module wires those two facts to the engine. Hidden tests are read from the task
directory and never from the workspace, so an agent cannot influence what is
used to judge it.
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from akbench.datasets.dataset import LoadedTask
from akbench.evaluators.engine import EvaluationResult, EvaluationVerdict, EvaluatorEngine
from akbench.evaluators.registry import EvaluatorRegistry, default_registry


def hidden_tests_dir(loaded: LoadedTask) -> Path:
    """The task's hidden tests, resolved inside the task directory."""
    return Path(loaded.path) / loaded.task.task.hidden_tests


def evaluate_task(
    loaded: LoadedTask,
    workspace: Path,
    out_dir: Path,
    *,
    evaluator_id: str | None = None,
    registry: EvaluatorRegistry | None = None,
    timeout: float | None = None,
    baseline: dict[str, str] | None = None,
) -> EvaluationResult:
    """Judge what the agent produced in ``workspace`` for ``loaded``.

    ``evaluator_id`` overrides the task's own choice (useful to add a
    supplementary evaluator); by default the evaluator named in the task runs,
    so a verdict always belongs to the task definition.
    """
    engine = EvaluatorEngine(registry or default_registry())
    tests = hidden_tests_dir(loaded)
    return engine.evaluate(
        evaluator_id or loaded.task.evaluator,
        workspace,
        out_dir=out_dir,
        timeout=timeout,
        hidden_tests=tests if tests.is_dir() else None,
        baseline=baseline,
    )


def capture_baseline(
    loaded: LoadedTask,
    workspace: Path,
    *,
    registry: EvaluatorRegistry | None = None,
    timeout: float | None = None,
) -> dict[str, str]:
    """Record which tests pass on ``workspace``, as a regression reference.

    Identifiers use the JUnit shape the evaluator reports, so a later run's
    failing tests can be intersected with this mapping. A workspace on which the
    evaluation does not fully pass yields an empty mapping: a baseline built on
    a broken base state would turn every later result into a false regression.
    """
    engine = EvaluatorEngine(registry or default_registry())
    tests = hidden_tests_dir(loaded)
    result = engine.evaluate(
        loaded.task.evaluator,
        workspace,
        out_dir=Path(tempfile.mkdtemp(prefix="akbench-baseline-")),
        timeout=timeout,
        hidden_tests=tests if tests.is_dir() else None,
    )
    report = result.artifacts.get("junit_xml")
    if result.verdict is not EvaluationVerdict.PASSED or not report:
        return {}
    return dict.fromkeys(_passing_names(Path(report)), "passed")


def _passing_names(report: Path) -> list[str]:
    try:
        root = ElementTree.parse(report).getroot()
    except (OSError, ElementTree.ParseError):
        return []
    passing: list[str] = []
    for case in root.iter("testcase"):
        if not any(child.tag in ("failure", "error", "skipped") for child in case):
            name = case.get("name") or "unknown"
            classname = case.get("classname")
            passing.append(f"{classname}::{name}" if classname else name)
    return passing

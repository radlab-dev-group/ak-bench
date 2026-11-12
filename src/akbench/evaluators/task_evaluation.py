"""Evaluating a task result (plan sections 8.6 and 16).

The task says which evaluator judges it and where its hidden tests live; this
module wires those two facts to the engine. Hidden tests are read from the task
directory and never from the workspace, so an agent cannot influence what is
used to judge it.

A task may name more than one evaluator. They then run in the order declared
and their verdicts are combined here, because the combination is a property of
the task definition and not of any one evaluator:

* a measurement that could not be made (``evaluator_error``,
  ``infrastructure_error``) wins over everything else, and over every other
  verdict it arrived with — a broken instrument says nothing about the agent;
* the verdicts that decide the task are the hard ones, those reporting
  ``pass_fail``. The first non-passing verdict in the declared order is the
  task's verdict;
* a score-valued evaluator (``static_analysis_evaluator``,
  ``diff_evaluator``) is a signal, never a verdict: on its own it cannot make
  a task fail, but it can keep a fully passing run from claiming a clean pass,
  which is what ``partial`` is for.
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

from akbench.datasets.dataset import LoadedTask
from akbench.evaluators.engine import EvaluationResult, EvaluationVerdict, EvaluatorEngine
from akbench.evaluators.registry import EvaluatorRegistry, default_registry

#: The ``kind`` of the evaluators that report a signal rather than a verdict.
#: Both of their descriptors say the same thing in prose — a finding is a
#: reason to look, not proof the task was not solved. They inform the combined
#: result; they do not decide it.
ADVISORY_KINDS = frozenset({"static_analysis", "diff"})

#: Verdicts saying the measurement, not the agent, failed.
MEASUREMENT_FAILURES = frozenset(
    {EvaluationVerdict.EVALUATOR_ERROR, EvaluationVerdict.INFRASTRUCTURE_ERROR}
)


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
    **evaluator_inputs: object,
) -> EvaluationResult:
    """Judge what the agent produced in ``workspace`` for ``loaded``.

    ``evaluator_id`` overrides the task's own choice (useful to add a
    supplementary evaluator); by default the evaluator named in the task runs,
    so a verdict always belongs to the task definition.

    ``evaluator_inputs`` carries the supplementary evaluator's own subject:
    the ``reference_patch`` the diff evaluator measures against, the ``script``
    the Python evaluator runs, the analyser ``command`` for static analysis.
    Every evaluator accepts unknown keywords and ignores them, so one call
    serves all five kinds without the caller knowing which one it is.
    """
    declared = [evaluator_id] if evaluator_id else list(loaded.task.evaluators)
    per_evaluator = {} if evaluator_id else loaded.task.task.evaluator_inputs
    engine = EvaluatorEngine(registry or default_registry())
    tests = hidden_tests_dir(loaded)

    if len(declared) == 1:
        return engine.evaluate(
            declared[0],
            workspace,
            out_dir=out_dir,
            timeout=timeout,
            hidden_tests=tests if tests.is_dir() else None,
            baseline=baseline,
            **{**per_evaluator.get(_bare(declared[0]), {}), **evaluator_inputs},
        )

    # More than one measurement: each gets its own output directory so their
    # raw reports, which are named after the evaluator's own artefacts, cannot
    # overwrite one another.
    results: list[tuple[str, EvaluationResult]] = []
    for reference in declared:
        identity = _bare(reference)
        results.append(
            (
                reference,
                engine.evaluate(
                    reference,
                    workspace,
                    out_dir=Path(out_dir) / identity,
                    timeout=timeout,
                    hidden_tests=tests if tests.is_dir() else None,
                    baseline=baseline,
                    **{**per_evaluator.get(identity, {}), **evaluator_inputs},
                ),
            )
        )
    return combine(loaded, results, registry or default_registry())


def _bare(reference: str) -> str:
    """The id part of an ``id@version`` reference."""
    return reference.split("@", 1)[0]


def combine(
    loaded: LoadedTask,
    results: list[tuple[str, EvaluationResult]],
    registry: EvaluatorRegistry,
) -> EvaluationResult:
    """One verdict for a task from the several its evaluators reported."""

    def kind_of(reference: str) -> str:
        try:
            return getattr(registry.resolve(_bare(reference)), "kind", "")
        except Exception:
            # An evaluator that cannot be resolved is a measurement failure in
            # its own right; treat it as a hard one so it is never waved off.
            return ""

    advisories = {reference for reference, _ in results if kind_of(reference) in ADVISORY_KINDS}

    components = [
        {
            "reference": reference,
            "evaluator_id": result.evaluator_id,
            "verdict": result.verdict.value,
            "score": result.score,
            "advisory": reference in advisories,
        }
        for reference, result in results
    ]
    raw = "\n\n".join(
        f"--- {reference} ({result.verdict.value}) ---\n{result.raw or ''}"
        for reference, result in results
    )
    artifacts: dict[str, str] = {}
    for reference, result in results:
        for name, value in result.artifacts.items():
            artifacts[f"{_bare(reference)}:{name}"] = value

    def merged(reference: str, verdict: EvaluationVerdict, reason: str) -> EvaluationResult:
        return _merged(
            loaded,
            reference,
            verdict,
            components,
            raw=raw,
            artifacts=artifacts,
            reason=reason,
        )

    # 1. A measurement that could not be made says nothing about the agent, and
    #    it is the only thing worth reporting first.
    for reference, result in results:
        if result.verdict in MEASUREMENT_FAILURES:
            return merged(
                reference, result.verdict, f"{reference} could not measure the workspace"
            )

    # 2. The hard verdicts decide, in the order the task declared them.
    for reference, result in results:
        if reference not in advisories and result.verdict is not EvaluationVerdict.PASSED:
            return merged(reference, result.verdict, f"{reference} decided the task")

    # 3. Everything hard passed. A signal that did not come back clean keeps
    #    the run from claiming a clean pass, without failing it.
    noisy = [
        reference
        for reference, result in results
        if result.verdict is not EvaluationVerdict.PASSED
    ]
    if noisy:
        return merged(
            results[0][0],
            EvaluationVerdict.PARTIAL,
            "advisory evaluator reported findings: " + ", ".join(noisy),
        )

    return merged(results[0][0], EvaluationVerdict.PASSED, "all evaluators passed")


def _merged(
    loaded: LoadedTask,
    decided_by: str,
    verdict: EvaluationVerdict,
    components: list[dict[str, Any]],
    *,
    raw: str,
    artifacts: dict[str, str],
    reason: str,
) -> EvaluationResult:
    """The combined result: the deciding verdict, with every part kept visible.

    ``evaluator_id`` stays the task's primary, so a historical row still quotes
    one evaluator; ``details.declared_evaluators`` keeps the whole set the
    verdict was made of, which is what makes a combined verdict re-examinable.
    """
    scores = [item["score"] for item in components if item["score"] is not None]
    return EvaluationResult(
        evaluator_id=loaded.task.evaluator,
        evaluator_version="1.0.0",
        verdict=verdict,
        score=round(sum(scores) / len(scores), 4) if scores else None,
        details={
            "declared_evaluators": [item["reference"] for item in components],
            "evaluators": components,
            "decided_by": decided_by,
            "reason": reason,
        },
        raw=raw,
        artifacts=artifacts,
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

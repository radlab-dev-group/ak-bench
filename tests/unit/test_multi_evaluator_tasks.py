"""A task judged by more than one evaluator.

A task may declare a list of evaluators; the verdict is then composed, and the
composition is where the subtlety lives. The rules this suite pins down are the
ones stated in `akbench.evaluators.task_evaluation`: a measurement that could
not be made outranks everything; the hard (pass/fail) evaluators decide; a
score-valued signal can dim a pass to a partial but can never fail a task on
its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from akbench.datasets.dataset import LoadedTask
from akbench.datasets.task import RepositorySpec, TaskBody, TaskDescriptor
from akbench.evaluators.engine import EvaluationResult, EvaluationVerdict
from akbench.evaluators.registry import default_registry
from akbench.evaluators.task_evaluation import combine

PYTEST = "pytest_evaluator"
STATIC = "static_analysis_evaluator"
COMMAND = "command_evaluator"


def task_with(evaluator: object, **inputs: object) -> LoadedTask:
    """A minimal task declaring ``evaluator`` — a bare id or a list of them."""
    body = TaskBody(
        category="performance",
        difficulty="hard",
        repository=RepositorySpec(source="datasets/_sources/wordcount", ref="HEAD"),
        evaluator=evaluator,
        evaluator_inputs=dict(inputs) if inputs else {},
    )
    descriptor = TaskDescriptor(id="multi-evaluator-001", version="1.0.0", task=body)
    return LoadedTask(task=descriptor, path=Path("/tmp/multi-evaluator-001"), digest="sha256:x")


def verdict_of(evaluator_id: str, verdict: EvaluationVerdict, **rest: object) -> EvaluationResult:
    return EvaluationResult(evaluator_id=evaluator_id, evaluator_version="1.0.0", verdict=verdict, **rest)


# --------------------------------------------------------------------------
# the descriptor accepts one evaluator or several, and stays backward compatible


def test_a_single_evaluator_id_still_loads_as_one() -> None:
    loaded = task_with(PYTEST)
    assert loaded.task.evaluators == [PYTEST]
    assert loaded.task.evaluator == PYTEST


def test_a_list_keeps_its_order_and_its_primary() -> None:
    loaded = task_with([PYTEST, COMMAND])
    assert loaded.task.evaluators == [PYTEST, COMMAND]
    # The primary is the first declared: it is what a single-valued reader quotes.
    assert loaded.task.evaluator == PYTEST


def test_an_evaluator_may_be_declared_only_once() -> None:
    with pytest.raises(ValidationError, match="only once"):
        task_with([PYTEST, PYTEST])


def test_an_empty_evaluator_list_is_refused() -> None:
    with pytest.raises(ValidationError):
        task_with([])


def test_inputs_are_read_back_per_evaluator() -> None:
    loaded = task_with(
        [PYTEST, COMMAND],
        **{COMMAND: {"command": "python tools/bench.py --json"}},
    )
    assert loaded.task.task.inputs_for(COMMAND) == {"command": "python tools/bench.py --json"}
    assert loaded.task.task.inputs_for(PYTEST) == {}


# --------------------------------------------------------------------------
# the composition


def combine_of(loaded: LoadedTask, results: list[tuple[str, EvaluationResult]]):
    return combine(loaded, results, default_registry())


def test_every_hard_evaluator_passing_makes_the_task_pass() -> None:
    loaded = task_with([PYTEST, COMMAND])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.PASSED)),
            (COMMAND, verdict_of(COMMAND, EvaluationVerdict.PASSED)),
        ],
    )
    assert result.verdict is EvaluationVerdict.PASSED
    assert result.evaluator_id == PYTEST


def test_a_failing_hard_evaluator_decides_however_clean_the_others_are() -> None:
    loaded = task_with([PYTEST, COMMAND])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.FAILED, raw="2 failed")),
            (COMMAND, verdict_of(COMMAND, EvaluationVerdict.PASSED)),
        ],
    )
    assert result.verdict is EvaluationVerdict.FAILED
    assert result.details["decided_by"] == PYTEST


def test_a_static_analysis_finding_never_fails_a_passing_task() -> None:
    """The advisory rule: a finding is a reason to look, not a verdict."""
    loaded = task_with([PYTEST, STATIC])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.PASSED)),
            (STATIC, verdict_of(STATIC, EvaluationVerdict.PARTIAL, score=0.5, raw="F401 imported")),
        ],
    )
    assert result.verdict is EvaluationVerdict.PARTIAL
    assert result.details["decided_by"] == PYTEST


def test_a_finding_is_recorded_as_advisory_and_who_decided() -> None:
    loaded = task_with([PYTEST, STATIC])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.FAILED)),
            (STATIC, verdict_of(STATIC, EvaluationVerdict.PASSED, score=1.0)),
        ],
    )
    advisory = {item["evaluator_id"]: item["advisory"] for item in result.details["evaluators"]}
    assert advisory == {PYTEST: False, STATIC: True}


def test_a_broken_measurement_outranks_a_failing_test() -> None:
    """An instrument that broke says nothing about the agent; say that instead."""
    loaded = task_with([PYTEST, COMMAND])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.FAILED)),
            (COMMAND, verdict_of(COMMAND, EvaluationVerdict.INFRASTRUCTURE_ERROR)),
        ],
    )
    assert result.verdict is EvaluationVerdict.INFRASTRUCTURE_ERROR
    assert result.details["decided_by"] == COMMAND


def test_an_evaluator_error_is_never_reported_as_an_agent_failure() -> None:
    loaded = task_with([PYTEST, STATIC])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.PASSED)),
            (STATIC, verdict_of(STATIC, EvaluationVerdict.EVALUATOR_ERROR)),
        ],
    )
    assert result.verdict is EvaluationVerdict.EVALUATOR_ERROR


def test_every_part_survives_the_combination() -> None:
    """A combined verdict must stay re-examinable: both raw reports are kept."""
    loaded = task_with([PYTEST, COMMAND])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.FAILED, raw="pytest said this")),
            (COMMAND, verdict_of(COMMAND, EvaluationVerdict.PASSED, raw="command said this")),
        ],
    )
    assert "pytest said this" in result.raw
    assert "command said this" in result.raw
    assert result.details["declared_evaluators"] == [PYTEST, COMMAND]


def test_scores_of_the_parts_are_averaged_not_lost() -> None:
    loaded = task_with([PYTEST, STATIC])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.PASSED, score=1.0)),
            (STATIC, verdict_of(STATIC, EvaluationVerdict.PARTIAL, score=0.25)),
        ],
    )
    assert result.score == pytest.approx(0.625)


def test_an_artefact_of_each_evaluator_is_kept_under_its_own_name() -> None:
    loaded = task_with([PYTEST, COMMAND])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.PASSED, artifacts={"junit_xml": "/tmp/a.xml"})),
            (COMMAND, verdict_of(COMMAND, EvaluationVerdict.PASSED, artifacts={"output": "/tmp/b.txt"})),
        ],
    )
    assert result.artifacts == {
        f"{PYTEST}:junit_xml": "/tmp/a.xml",
        f"{COMMAND}:output": "/tmp/b.txt",
    }


def test_a_timeout_counts_as_a_hard_decision() -> None:
    loaded = task_with([PYTEST, COMMAND])
    result = combine_of(
        loaded,
        [
            (PYTEST, verdict_of(PYTEST, EvaluationVerdict.PASSED)),
            (COMMAND, verdict_of(COMMAND, EvaluationVerdict.TIMEOUT)),
        ],
    )
    assert result.verdict is EvaluationVerdict.TIMEOUT

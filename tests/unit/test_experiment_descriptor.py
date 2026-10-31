"""The experiment descriptor model: strictness and self-consistency (plan 12).

The descriptor is the researcher's declaration of intent, so a typo must fail
loudly: unknown keys are refused, contradictions inside the file are caught
before the planner sees them, and the values that survive are the ones a plan
will actually use.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from akbench.experiments import (
    DatasetSelection,
    ExecutionPolicy,
    ExperimentDescriptor,
    Factors,
    Isolation,
    Limits,
    parse_experiment,
)


def minimal(**overrides: object) -> ExperimentDescriptor:
    document: dict[str, object] = {
        "schema_version": "1.0",
        "id": "test-experiment",
        "version": "1.0.0",
        "experiment": {"agent": {"id": "codex"}},
    }
    document["experiment"].update(overrides)  # type: ignore[union-attr]
    return parse_experiment(document).descriptor


def test_a_minimal_experiment_is_valid() -> None:
    descriptor = minimal()

    assert descriptor.identity() == "test-experiment@1.0.0"
    assert descriptor.agent_id == "codex"
    assert descriptor.repetitions == 1
    assert descriptor.strategy.value == "full_factorial"


def test_an_unknown_key_is_refused() -> None:
    from akbench.experiments import ExperimentError

    with pytest.raises(ExperimentError, match="Extra inputs are not permitted"):
        parse_experiment(
            {
                "schema_version": "1.0",
                "id": "x",
                "version": "1",
                "experiment": {"agent": {"id": "codex"}, "typo": True},
            }
        )


def test_an_unsupported_schema_version_is_refused() -> None:
    from akbench.experiments import ExperimentError

    with pytest.raises(ExperimentError, match="schema_version"):
        parse_experiment(
            {
                "schema_version": "0.9",
                "id": "x",
                "version": "1",
                "experiment": {"agent": {"id": "codex"}},
            }
        )


def test_agent_retries_must_stay_zero() -> None:
    with pytest.raises(ValidationError, match="retry_agent_failures must be 0"):
        ExecutionPolicy(retry_agent_failures=1)


def test_isolation_cannot_be_relaxed() -> None:
    with pytest.raises(ValidationError, match="workspace_per_run cannot be false"):
        Isolation(workspace_per_run=False)


def test_a_clean_context_requires_a_fresh_session() -> None:
    with pytest.raises(ValidationError, match="fresh_agent_session"):
        Isolation(fresh_agent_session=False, clean_agent_context=True)


def test_runtime_and_direct_mode_do_not_mix() -> None:
    from akbench.experiments import ExperimentError

    with pytest.raises(
        ExperimentError, match="name a runtime only in runtime or router mode"
    ):
        minimal(execution={"mode": "direct", "runtime": {"id": "llm-router"}})


def test_repititions_are_bounded() -> None:
    assert ExecutionPolicy(repetitions=1).repetitions == 1
    with pytest.raises(ValidationError, match="repetitions"):
        ExecutionPolicy(repetitions=0)
    with pytest.raises(ValidationError, match="repetitions"):
        ExecutionPolicy(repetitions=1001)


def test_duplicate_factors_are_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate dimensions"):
        Factors(dimensions=[{"id": "model"}, {"id": "model"}])


def test_repetition_is_reserved_and_not_a_factor() -> None:
    with pytest.raises(ValidationError, match="is not a factor"):
        Factors(dimensions=[{"id": "repetition"}])


def test_custom_matrix_needs_its_rows() -> None:
    with pytest.raises(ValidationError, match="combinations"):
        Factors(strategy="custom_matrix")


def test_custom_matrix_is_the_only_strategy_that_takes_rows() -> None:
    with pytest.raises(ValidationError, match="only meaningful with strategy custom_matrix"):
        Factors(strategy="full_factorial", combinations=[{"model": "a"}])


def test_selected_factors_needs_a_selection() -> None:
    with pytest.raises(ValidationError, match=r"requires factors\.selected"):
        Factors(strategy="selected_factors", dimensions=[{"id": "model"}])


def test_selected_names_must_be_declared() -> None:
    with pytest.raises(ValidationError, match="not declared"):
        Factors(
            strategy="selected_factors",
            dimensions=[{"id": "model"}],
            selected=["nope"],
        )


def test_selected_is_only_meaningful_with_its_strategy() -> None:
    with pytest.raises(ValidationError, match="only meaningful with strategy selected_factors"):
        Factors(strategy="full_factorial", dimensions=[{"id": "model"}], selected=["model"])


def test_a_baseline_must_name_a_factor() -> None:
    with pytest.raises(ValidationError, match="not a declared factor"):
        Factors(dimensions=[{"id": "model"}], baseline={"nope": "a"})


def test_factor_values_must_not_be_empty() -> None:
    with pytest.raises(ValidationError, match="must not be an empty list"):
        Factors(dimensions=[{"id": "model", "values": []}])


def test_limits_are_positive() -> None:
    assert Limits(max_runs=1).max_runs == 1
    with pytest.raises(ValidationError, match="max_runs"):
        Limits(max_runs=0)


def test_evaluation_baseline_is_a_closed_set() -> None:
    from akbench.experiments import ExperimentError

    document = minimal()
    assert document.experiment.evaluation.baseline is None
    with pytest.raises(ExperimentError, match="base_state"):
        minimal(evaluation={"baseline": "whatever"})


def test_dataset_filters_default_to_everything() -> None:
    selection = DatasetSelection()

    assert selection.filters.categories == []
    assert selection.filters.difficulties == []
    assert selection.filters.task_ids == []


def test_the_descriptor_is_versioned_like_any_other() -> None:
    descriptor = minimal()

    snapshot = descriptor.to_snapshot()
    assert snapshot["id"] == "test-experiment"
    assert snapshot["version"] == "1.0.0"
    assert snapshot["schema_version"] == "1.0"

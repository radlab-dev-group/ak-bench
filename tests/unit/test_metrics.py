"""Metrics (plan section 18): a measurement, not a statement.

The tests guard the honesty rules: an unmeasured metric is ``unavailable`` with
a reason, a rate is computed only over the runs that reported it, an
efficiency gain never masquerades as a quality gain, and the baseline deltas
follow the plan's formulas.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from akbench.core.errors import DescriptorError
from akbench.descriptors import MetricDescriptor, load_registry
from akbench.metrics import MetricCatalog, aggregate_runs, baseline_deltas, collect_run_metrics
from akbench.metrics.collect import UNAVAILABLE

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalog() -> MetricCatalog:
    return MetricCatalog.from_registry(load_registry(REPO_ROOT / "descriptors"))


def _record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_uid": "run-1",
        "agent_id": "codex",
        "agent_version": "0.9.0",
        "state": "completed",
        "session_id": "thread-1",
        "started_at": "2026-10-31T09:00:00+00:00",
        "finished_at": "2026-10-31T09:01:00+00:00",
        "evaluation": {
            "verdict": "passed",
            "score": 1.0,
            "passed": 8,
            "failed": 0,
            "total": 8,
        },
    }
    base.update(overrides)
    return base


def _observations(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "token_usage": {
            "input_tokens": 3000,
            "cached_input_tokens": 1000,
            "output_tokens": 1000,
            "reasoning_output_tokens": 200,
            "total_tokens": 4000,
        },
        "tool_names": {"exec_command": 6},
    }
    base.update(overrides)
    return base


def _collect(
    catalog: MetricCatalog,
    record: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    return collect_run_metrics(record, catalog, observations=observations)


# ------------------------------------------------------------------- catalog


def test_catalog_loads_the_shipped_metrics(catalog: MetricCatalog) -> None:
    names = set(catalog.names())
    assert "task_success_rate" in names
    assert "knowledge_hit_rate" in names
    assert catalog.get("total_cost").metric.availability.value == "unavailable"
    with pytest.raises(KeyError):
        catalog.get("no_such_metric")


def test_catalog_rejects_duplicate_metric_ids() -> None:
    first = MetricDescriptor.model_validate(
        {
            "schema_version": "1.0",
            "id": "dup",
            "version": "1.0.0",
            "title": "A",
            "metric": {"group": "quality"},
        }
    )
    with pytest.raises(DescriptorError, match="duplicate metric"):
        MetricCatalog([first, first])


def test_catalog_splits_computable_from_unavailable(catalog: MetricCatalog) -> None:
    computable = {item.id for item in catalog.computable()}
    unavailable = {item.id for item in catalog.unavailable()}
    assert computable.isdisjoint(unavailable)
    assert "total_cost" in unavailable
    assert "execution_time" in computable
    assert set(computable) | set(unavailable) == set(catalog.names())


# ------------------------------------------------------------------ quality


def test_quality_metrics_come_from_the_verdict(catalog: MetricCatalog) -> None:
    values = _collect(catalog, _record(), _observations())

    assert values["task_success_rate"].value == 1.0
    assert values["partial_success_rate"].value == 0.0
    assert values["regression_rate"].value == 0.0
    assert values["hidden_test_pass_rate"].value == 1.0
    assert values["evaluator_score"].value == 1.0


def test_a_partial_run_is_never_counted_as_a_success(catalog: MetricCatalog) -> None:
    record = _record(evaluation={"verdict": "partial", "passed": 5, "failed": 3, "total": 8})
    values = _collect(catalog, record, _observations())

    assert values["task_success_rate"].value == 0.0
    assert values["partial_success_rate"].value == 1.0
    assert values["hidden_test_pass_rate"].value == pytest.approx(5 / 8)


def test_a_run_without_an_evaluation_reports_no_quality(catalog: MetricCatalog) -> None:
    values = _collect(catalog, _record(evaluation=None), _observations())

    assert values["task_success_rate"].availability == UNAVAILABLE
    assert "no evaluation" in (values["task_success_rate"].reason or "")


def test_a_command_evaluator_cannot_report_a_pass_rate(catalog: MetricCatalog) -> None:
    record = _record(evaluation={"verdict": "passed", "passed": None, "total": None})
    values = _collect(catalog, record, _observations())

    assert values["hidden_test_pass_rate"].availability == UNAVAILABLE
    assert "verdict" in (values["hidden_test_pass_rate"].reason or "")


# --------------------------------------------------------------- efficiency


def test_efficiency_metrics_come_from_usage_and_timing(catalog: MetricCatalog) -> None:
    values = _collect(catalog, _record(), _observations())

    assert values["execution_time"].value == pytest.approx(60.0)
    assert values["input_tokens"].value == 3000
    assert values["total_tokens"].value == 4000
    assert values["tool_call_count"].value == 6
    assert values["total_cost"].availability == UNAVAILABLE
    assert "cost" in (values["total_cost"].reason or "")


def test_missing_usage_is_unavailable_not_zero(catalog: MetricCatalog) -> None:
    values = _collect(catalog, _record(), {})

    assert values["input_tokens"].availability == UNAVAILABLE
    assert values["input_tokens"].value is None
    assert "token usage" in (values["input_tokens"].reason or "")


def test_an_unfinished_run_has_no_execution_time(catalog: MetricCatalog) -> None:
    values = _collect(catalog, _record(finished_at=None), _observations())
    assert values["execution_time"].availability == UNAVAILABLE


# ------------------------------------------------------------ agent runtime


def test_agent_runtime_metrics_are_recorded(catalog: MetricCatalog) -> None:
    values = _collect(catalog, _record(), _observations())

    assert values["agent_identity"].value == "codex@0.9.0"
    assert values["session_id"].value == "thread-1"
    assert values["run_status"].value == "completed"
    assert values["incomplete_trace_rate"].value == 0.0
    assert values["observed_model"].availability == UNAVAILABLE


def test_a_run_without_a_session_has_an_incomplete_trace(catalog: MetricCatalog) -> None:
    values = _collect(catalog, _record(session_id=None), _observations())
    assert values["incomplete_trace_rate"].value == 1.0


# --------------------------------------------------------------- reliability


def test_a_failed_task_is_not_a_crash(catalog: MetricCatalog) -> None:
    record = _record(state="failed", failure_class="agent", exit_code=1)
    values = _collect(catalog, record, _observations())

    assert values["agent_crash_rate"].value == 0.0
    assert values["infrastructure_failure_rate"].value == 0.0


def test_an_agent_killed_by_a_signal_is_a_crash(catalog: MetricCatalog) -> None:
    record = _record(state="failed", failure_class="agent", exit_code=-9)
    values = _collect(catalog, record, _observations())
    assert values["agent_crash_rate"].value == 1.0


def test_infrastructure_failures_are_counted_apart(catalog: MetricCatalog) -> None:
    record = _record(state="infrastructure_error", failure_class="infrastructure")
    values = _collect(catalog, record, _observations())

    assert values["infrastructure_failure_rate"].value == 1.0
    assert values["agent_crash_rate"].value == 0.0


def test_timeouts_are_their_own_reliability_column(catalog: MetricCatalog) -> None:
    record = _record(state="timeout")
    values = _collect(catalog, record, _observations())
    assert values["timeout_rate"].value == 1.0


# -------------------------------------------------------------- plugin data


def test_plugin_metrics_flow_through_as_measured(catalog: MetricCatalog) -> None:
    values = collect_run_metrics(
        _record(),
        catalog,
        observations=_observations(),
        plugin_metrics={"knowledge_write_count": 4},
    )
    assert values["knowledge_write_count"].availability == "measured"
    assert values["knowledge_write_count"].value == 4
    assert values["knowledge_hit_rate"].availability == UNAVAILABLE


# ---------------------------------------------------------------- aggregation


def test_aggregation_keeps_the_missing_runs_visible(catalog: MetricCatalog) -> None:
    complete = _collect(catalog, _record(), _observations())
    bare = _collect(catalog, _record(), {})

    aggregate = aggregate_runs([complete, bare])
    entry = aggregate["input_tokens"]
    assert entry.runs == 2
    assert entry.measured == 1
    assert entry.availability == 0.5
    assert entry.mean == 3000
    assert entry.reasons, "the missing run must say why it is missing"


def test_aggregation_does_not_average_labels(catalog: MetricCatalog) -> None:
    first = _collect(catalog, _record(agent_id="codex"), _observations())
    second = _collect(catalog, _record(agent_id="claude"), _observations())

    aggregate = aggregate_runs([first, second])
    identity = aggregate["agent_identity"]
    assert identity.mean is None
    assert set(identity.values) == {"codex@0.9.0", "claude@0.9.0"}


def test_an_aggregate_over_nothing_reports_nothing() -> None:
    aggregate = aggregate_runs([])
    assert aggregate == {}


# -------------------------------------------------------------------- deltas


def _aggregate(
    catalog: MetricCatalog,
    records: list[Mapping[str, Any]],
    observations: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return aggregate_runs(
        [
            _collect(catalog, record, obs)
            for record, obs in zip(records, observations, strict=True)
        ]
    )


def test_delta_follows_the_plan_formulas(catalog: MetricCatalog) -> None:
    baseline = _aggregate(
        catalog,
        [_record()],
        [_observations()],
    )
    variant = _aggregate(
        catalog,
        [_record(
            finished_at="2026-10-31T09:00:20+00:00",
            evaluation={"verdict": "partial", "passed": 6, "failed": 2, "total": 8},
        )],
        [_observations(token_usage={"input_tokens": 900, "total_tokens": 1200})],
    )

    deltas = {item.metric: item for item in baseline_deltas(variant, baseline)}
    assert deltas["task_success_rate"].delta == "delta_success"
    assert deltas["task_success_rate"].value == pytest.approx(-1.0)
    assert deltas["execution_time"].delta == "speedup"
    assert deltas["execution_time"].value == pytest.approx(3.0)
    assert deltas["total_tokens"].delta == "token_saving"
    assert deltas["total_tokens"].value == pytest.approx(0.7)
    assert deltas["total_tokens"].note is not None


def test_a_zero_baseline_uses_an_absolute_difference(catalog: MetricCatalog) -> None:
    baseline = _aggregate(catalog, [_record()], [_observations(token_usage={"total_tokens": 0})])
    variant = _aggregate(catalog, [_record()], [_observations(token_usage={"total_tokens": 10})])

    delta = next(
        item for item in baseline_deltas(variant, baseline) if item.metric == "total_tokens"
    )
    assert delta.value == pytest.approx(10.0)
    assert "absolute difference" in delta.formula


def test_an_unmeasured_side_yields_no_number(catalog: MetricCatalog) -> None:
    baseline = _aggregate(catalog, [_record()], [_observations()])
    variant = _aggregate(catalog, [_record()], [{}])

    delta = next(
        item for item in baseline_deltas(variant, baseline) if item.metric == "total_tokens"
    )
    assert delta.value is None
    assert delta.note is not None

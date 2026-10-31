"""Per-run metric collection (plan section 18).

A metric is collected only when the run actually carries the data for it.
Everything else comes back ``unavailable`` with the reason taken from the
metric descriptor, because a zero would read as "knowledge was not used" or
"the run cost nothing" — claims the evidence does not support.

The collector reads plain records (a run record, agent observations, plugin
metrics), so it works on a live run and on a run loaded from disk or an export.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from akbench.metrics.catalog import MetricCatalog

#: Availability of a value for one run. ``unavailable`` always carries a reason.
MEASURED = "measured"
DERIVED = "derived"
UNAVAILABLE = "unavailable"

NO_EVALUATION = "the run produced no evaluation result"
NO_USAGE = "the agent reported no token usage for this run"
NO_OBSERVATIONS = "the agent produced no observations for this run"


@dataclass(frozen=True)
class MetricValue:
    """The value of one metric for one run, with its provenance."""

    name: str
    group: str
    value: Any | None = None
    unit: str | None = None
    availability: str = MEASURED
    reason: str | None = None
    source: str | None = None

    @property
    def measured(self) -> bool:
        return self.availability != UNAVAILABLE and self.value is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "group": self.group,
            "value": self.value,
            "unit": self.unit,
            "availability": self.availability,
            "reason": self.reason,
            "source": self.source,
        }


def _evaluation(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    evaluation = record.get("evaluation")
    return evaluation if isinstance(evaluation, Mapping) else None


def _verdict(record: Mapping[str, Any]) -> str | None:
    evaluation = _evaluation(record)
    verdict = evaluation.get("verdict") if evaluation else None
    return str(verdict) if verdict is not None else None


def _indicator(condition: bool) -> float:
    """A per-run 0/1 indicator; the mean over runs is the rate."""
    return 1.0 if condition else 0.0


def _execution_seconds(record: Mapping[str, Any]) -> float | None:
    start, end = record.get("started_at"), record.get("finished_at")
    if not isinstance(start, (str, datetime)) or not isinstance(end, (str, datetime)):
        return None
    try:
        started = datetime.fromisoformat(str(start))
        finished = datetime.fromisoformat(str(end))
    except ValueError:
        return None
    if started.tzinfo is None or finished.tzinfo is None:
        return None
    seconds = (finished - started).total_seconds()
    return round(seconds, 3) if seconds >= 0 else None


def _token_field(observations: Mapping[str, Any], field: str) -> int | None:
    usage = observations.get("token_usage")
    if not isinstance(usage, Mapping):
        return None
    value = usage.get(field)
    return value if isinstance(value, int) else None


def _identity(record: Mapping[str, Any]) -> str | None:
    agent_id = record.get("agent_id")
    if not agent_id:
        return None
    version = record.get("agent_version")
    return f"{agent_id}@{version}" if version else str(agent_id)


def _trace_incomplete(record: Mapping[str, Any], observations: Mapping[str, Any]) -> bool:
    """A trace is incomplete when the run has no readable session or errored.

    The rollout file is a side effect of session persistence, so a missing
    session id means the trace cannot be reconstructed (a measured fact about
    the trace, not an inference about the agent).
    """
    if not record.get("session_id"):
        return True
    return bool(observations.get("stream_error"))


#: metric id -> resolver(record, observations) -> value or None.
Resolvers: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = {
    "task_success_rate": lambda record, obs: (
        _indicator(_verdict(record) == "passed") if _evaluation(record) else None
    ),
    "partial_success_rate": lambda record, obs: (
        _indicator(_verdict(record) == "partial") if _evaluation(record) else None
    ),
    "regression_rate": lambda record, obs: (
        _indicator(_verdict(record) == "regression") if _evaluation(record) else None
    ),
    "hidden_test_pass_rate": lambda record, obs: _hidden_test_rate(record),
    "evaluator_score": lambda record, obs: (
        _evaluation(record).get("score") if _evaluation(record) else None
    ),
    "execution_time": lambda record, obs: _execution_seconds(record),
    "input_tokens": lambda record, obs: _token_field(obs, "input_tokens"),
    "cached_input_tokens": lambda record, obs: _token_field(obs, "cached_input_tokens"),
    "output_tokens": lambda record, obs: _token_field(obs, "output_tokens"),
    "reasoning_output_tokens": lambda record, obs: _token_field(obs, "reasoning_output_tokens"),
    "total_tokens": lambda record, obs: _token_field(obs, "total_tokens"),
    "tool_call_count": lambda record, obs: _tool_call_count(obs),
    "agent_identity": lambda record, obs: _identity(record),
    "session_id": lambda record, obs: record.get("session_id"),
    "run_status": lambda record, obs: record.get("state") or record.get("run_status"),
    "observed_model": lambda record, obs: obs.get("observed_model"),
    "timeout_rate": lambda record, obs: (
        _indicator((record.get("state") or "") == "timeout") if record.get("state") else None
    ),
    "infrastructure_failure_rate": lambda record, obs: (
        _indicator(record.get("failure_class") == "infrastructure")
        if record.get("state")
        else None
    ),
    "agent_crash_rate": lambda record, obs: _agent_crash(record, obs),
    "incomplete_trace_rate": lambda record, obs: (
        _indicator(_trace_incomplete(record, obs)) if record.get("state") else None
    ),
}

#: Reasons that depend on the run, not on the metric definition.
_CONDITIONAL_REASONS: dict[str, str] = {
    "router_error_rate": (
        "router error counters are global to the shared instance, so they describe the "
        "environment during the run, not the run itself; pass runtime observations to "
        "collect them"
    ),
}


def _hidden_test_rate(record: Mapping[str, Any]) -> float | None:
    """Pass ratio of the hidden tests, or ``None`` when they never ran.

    Only the pytest evaluator reports per-test counts; a command evaluator
    answers pass/fail for the whole task, which is a verdict, not a rate.
    """
    evaluation = _evaluation(record)
    if evaluation is None:
        return None
    passed, total = evaluation.get("passed"), evaluation.get("total")
    if not isinstance(passed, int) or not isinstance(total, int) or total <= 0:
        return None
    return round(passed / total, 6)


def _tool_call_count(observations: Mapping[str, Any]) -> int | None:
    count = observations.get("tool_call_count")
    if isinstance(count, int):
        return count
    names = observations.get("tool_names")
    if isinstance(names, Mapping) and names:
        total = sum(value for value in names.values() if isinstance(value, int))
        return total
    return None


def _agent_crash(record: Mapping[str, Any], observations: Mapping[str, Any]) -> float | None:
    """A crash is an agent-side failure that ended the process abnormally.

    A non-zero exit code alone is not a crash: an agent that fails a task also
    exits non-zero, and conflating the two would move a measured outcome into
    the reliability column (plan rule 11).
    """
    if record.get("failure_class") != "agent":
        return _indicator(False) if record.get("state") else None
    exit_code = record.get("exit_code")
    killed_by_signal = isinstance(exit_code, int) and exit_code < 0
    return _indicator(bool(observations.get("stream_error")) or killed_by_signal)


def collect_run_metrics(
    record: Mapping[str, Any],
    catalog: MetricCatalog,
    observations: Mapping[str, Any] | None = None,
    plugin_metrics: Mapping[str, Any] | None = None,
    runtime_observations: Mapping[str, Any] | None = None,
) -> dict[str, MetricValue]:
    """Every catalog metric for one run, measured or honestly unavailable.

    ``plugin_metrics`` carries values a plugin adapter did manage to measure
    (keyed by metric name); a metric the plugin cannot expose stays
    unavailable with the descriptor's reason.
    """
    observed = dict(observations or {})
    from_plugins = dict(plugin_metrics or {})
    runtime = dict(runtime_observations or {})

    values: dict[str, MetricValue] = {}
    for descriptor in catalog.all():
        group = descriptor.metric.group.value
        unit = descriptor.metric.unit
        name = descriptor.id

        if name in from_plugins:
            values[name] = MetricValue(
                name=name,
                group=group,
                value=from_plugins[name],
                unit=unit,
                availability=MEASURED,
                source="plugin adapter",
            )
            continue
        if name in runtime:
            values[name] = MetricValue(
                name=name,
                group=group,
                value=runtime[name],
                unit=unit,
                availability=DERIVED,
                source="runtime observations",
            )
            continue
        if not descriptor.computable:
            values[name] = MetricValue(
                name=name,
                group=group,
                unit=unit,
                availability=UNAVAILABLE,
                reason=descriptor.metric.unavailable_reason or "the metric has no source",
            )
            continue

        resolver = Resolvers.get(name)
        if resolver is None:
            values[name] = MetricValue(
                name=name,
                group=group,
                unit=unit,
                availability=UNAVAILABLE,
                reason="no collector implements this metric",
            )
            continue

        value = resolver(record, observed)
        if value is None:
            values[name] = MetricValue(
                name=name,
                group=group,
                unit=unit,
                availability=UNAVAILABLE,
                reason=_missing_reason(name, record, observed),
            )
        else:
            derived = descriptor.metric.availability.value == "derived"
            availability = DERIVED if derived else MEASURED
            values[name] = MetricValue(
                name=name,
                group=group,
                value=value,
                unit=unit,
                availability=availability,
            )
    return values


def _missing_reason(name: str, record: Mapping[str, Any], observations: Mapping[str, Any]) -> str:
    if name in _CONDITIONAL_REASONS:
        return _CONDITIONAL_REASONS[name]
    if name in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
        return NO_USAGE
    if name in ("task_success_rate", "partial_success_rate", "regression_rate", "evaluator_score"):
        return NO_EVALUATION
    if name == "hidden_test_pass_rate":
        return (
            "the evaluator reported no per-test counts; a command evaluator reports a "
            "verdict, not a rate"
        )
    if name == "tool_call_count":
        return NO_OBSERVATIONS if not observations else "the agent reported no tool calls"
    if name == "execution_time":
        return "the run record has no usable start and finish timestamps"
    if name == "observed_model":
        return "the model that served the request was not observable for this run"
    if name in ("session_id", "run_status", "agent_identity"):
        return "the run record does not carry this field"
    return "the run did not produce this data"

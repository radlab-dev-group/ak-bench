"""Aggregation over runs and baseline comparison (plan section 18).

Two rules decide the shape of everything here:

- a rate is only a rate over the runs that actually reported the value, and
  the number of missing runs is reported next to it (an average over two of
  ten runs must not look like an average over ten);
- a saving is not a success. Efficiency deltas are computed and reported, but
  they never override a quality delta, and the output says so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from akbench.metrics.collect import MetricValue

#: Read alongside every efficiency delta (plan section 18).
INTERPRETATION_NOTE = (
    "a shorter or cheaper run is not a better run: read speedup and token_saving "
    "together with the quality deltas"
)

#: metric id -> (delta name, formula). Anything else falls back to a difference.
DELTA_FORMULAS = {
    "task_success_rate": ("delta_success", "variant - baseline"),
    "hidden_test_pass_rate": ("delta_hidden_test_pass_rate", "variant - baseline"),
    "regression_rate": ("delta_regression_rate", "variant - baseline"),
    "execution_time": ("speedup", "baseline / variant"),
    "total_tokens": ("token_saving", "1 - variant / baseline"),
    "input_tokens": ("token_saving", "1 - variant / baseline"),
    "tool_call_count": ("delta_tool_call_count", "variant - baseline"),
}


@dataclass(frozen=True)
class AggregatedMetrics:
    """One metric across a set of runs.

    ``measured`` counts the runs that produced a value; ``availability`` is
    that share, so a mean computed over a handful of runs is never mistaken
    for a complete picture.
    """

    metric: str
    group: str
    unit: str | None = None
    runs: int = 0
    measured: int = 0
    availability: float | None = None
    mean: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    values: list[Any] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "group": self.group,
            "unit": self.unit,
            "runs": self.runs,
            "measured": self.measured,
            "availability": self.availability,
            "mean": self.mean,
            "min": self.minimum,
            "max": self.maximum,
            "values": list(self.values),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class BaselineDelta:
    """How a variant compares with a baseline run or set of runs."""

    metric: str
    delta: str
    formula: str
    variant_value: float | None = None
    baseline_value: float | None = None
    value: float | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "delta": self.delta,
            "formula": self.formula,
            "variant": self.variant_value,
            "baseline": self.baseline_value,
            "value": self.value,
            "note": self.note,
        }


def aggregate_runs(runs: Iterable[Mapping[str, MetricValue]]) -> dict[str, AggregatedMetrics]:
    """Aggregate one metric across runs; numbers and labels stay separate.

    Numeric metrics get a mean, a minimum and a maximum. Non-numeric ones
    (agent identity, run status) keep their per-run values: averaging labels
    would be invention.
    """
    collected = [list(run.values()) for run in runs]
    flat: dict[str, list[MetricValue]] = {}
    for values in collected:
        for value in values:
            flat.setdefault(value.name, []).append(value)

    aggregate: dict[str, AggregatedMetrics] = {}
    total = len(collected)
    for name, values in flat.items():
        measured = [item for item in values if item.measured]
        numbers = [item.value for item in measured if isinstance(item.value, (int, float))]
        group = values[0].group
        unit = values[0].unit
        aggregate[name] = AggregatedMetrics(
            metric=name,
            group=group,
            unit=unit,
            runs=total,
            measured=len(measured),
            availability=round(len(measured) / total, 6) if total else None,
            mean=round(mean(numbers), 6) if numbers else None,
            minimum=min(numbers) if numbers else None,
            maximum=max(numbers) if numbers else None,
            values=[item.value for item in measured if not isinstance(item.value, (int, float))],
            reasons=sorted({item.reason for item in values if item.reason}),
        )
    return aggregate


def baseline_deltas(
    variant: Mapping[str, AggregatedMetrics],
    baseline: Mapping[str, AggregatedMetrics],
) -> list[BaselineDelta]:
    """Compare a variant with a baseline using the plan's formulas (section 18).

    ``delta_success = success_variant - success_baseline``;
    ``speedup = time_baseline / time_variant``;
    ``token_saving = 1 - tokens_variant / tokens_baseline``, and when a
    baseline is zero the absolute difference is reported instead, because a
    ratio against zero has no meaning.
    """
    deltas: list[BaselineDelta] = []
    for name, variant_entry in variant.items():
        baseline_entry = baseline.get(name)
        if baseline_entry is None or variant_entry.group not in {"quality", "efficiency"}:
            continue
        deltas.append(_delta(name, variant_entry, baseline_entry))
    return deltas


def _delta(name: str, variant: AggregatedMetrics, baseline: AggregatedMetrics) -> BaselineDelta:
    delta, formula = DELTA_FORMULAS.get(name, (f"delta_{name}", "variant - baseline"))
    have = variant.mean
    reference = baseline.mean

    if have is None or reference is None:
        missing = _missing_note(variant, baseline)
        return BaselineDelta(
            metric=name,
            delta=delta,
            formula=formula,
            variant_value=have,
            baseline_value=reference,
            value=None,
            note=missing,
        )

    if formula == "baseline / variant":
        if have == 0:
            return BaselineDelta(
                metric=name,
                delta=delta,
                formula="baseline / variant (undefined: variant time is zero)",
                variant_value=have,
                baseline_value=reference,
                value=None,
                note="speedup is undefined when the variant reports a zero duration",
            )
        value = round(reference / have, 6)
    elif formula.startswith("1 - variant / baseline"):
        if reference == 0:
            return BaselineDelta(
                metric=name,
                delta=delta,
                formula="absolute difference (baseline is zero, a ratio would be undefined)",
                variant_value=have,
                baseline_value=reference,
                value=round(have - reference, 6),
                note="the baseline reports zero, so the absolute difference is shown instead",
            )
        value = round(1 - (have / reference), 6)
    else:
        value = round(have - reference, 6)

    return BaselineDelta(
        metric=name,
        delta=delta,
        formula=formula,
        variant_value=have,
        baseline_value=reference,
        value=value,
        note=INTERPRETATION_NOTE if "variant /" in formula or "baseline /" in formula else None,
    )


def _missing_note(variant: AggregatedMetrics, baseline: AggregatedMetrics) -> str:
    parts: list[str] = []
    if variant.mean is None:
        parts.append(f"the variant reported {name_count(variant)}")
    if baseline.mean is None:
        parts.append(f"the baseline reported {name_count(baseline)}")
    return "no comparison: " + " and ".join(parts)


def name_count(entry: AggregatedMetrics) -> str:
    """How little data a missing aggregate rests on, in plain words."""
    if entry.measured == 0:
        return f"no value in {entry.runs} run(s)"
    return "no usable numeric value"

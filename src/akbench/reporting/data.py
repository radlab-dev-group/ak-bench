"""The numbers behind the reports, computed from the recorded history only.

Nothing here asks an agent, a router or the network anything: a report is a
rendering of what was stored. Two rules run through the whole module.

- a missing value stays missing. Durations of runs that never started are not
  counted, an average says over how many runs it was computed, and a grouping
  with nothing measured reports ``None`` rather than zero;
- cost is not measured by this project. No price is recorded anywhere, so the
  cost block states that instead of multiplying tokens by a made-up rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PASSED_VERDICT = "passed"
RECENT_LIMIT = 5


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def duration_seconds(run: dict[str, Any]) -> float | None:
    """Wall-clock seconds of one run, or ``None`` when either end is missing."""
    started = _parse_time(run.get("started_at"))
    finished = _parse_time(run.get("finished_at"))
    if started is None or finished is None:
        return None
    return (finished - started).total_seconds()


def variant_lookup(variants: list[dict[str, Any]]) -> dict[str, Any]:
    """Map a variant uid to the factor values it names.

    A uid is unique inside one experiment, so a caller that mixes experiments
    passes the variants of all of them. Two experiments that gave the same uid
    different values cancel each other out and the uid disappears: the report
    then says the parameters were not recorded rather than guessing one.
    """
    lookup: dict[str, Any] = {}
    claimed: set[str] = set()
    for variant in variants:
        uid = str(variant.get("uid"))
        values = variant.get("values")
        if uid in lookup and lookup[uid] != values:
            claimed.add(uid)
            continue
        lookup[uid] = values
    for uid in claimed:
        lookup.pop(uid, None)
    return lookup


def _sortable_start(run: dict[str, Any]) -> tuple[int, str]:
    """A key that orders runs by when they started; a missing start is last."""
    started = _parse_time(run.get("started_at"))
    if started is None:
        return (1, "")
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return (0, started.astimezone(UTC).isoformat())


def order_by_start(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Runs in the order they started, the uid breaking a tie."""
    return sorted(runs, key=lambda run: (_sortable_start(run), str(run.get("uid") or "")))


def verdict_of(run: dict[str, Any]) -> str | None:
    evaluation = run.get("evaluation")
    if isinstance(evaluation, dict):
        verdict = evaluation.get("verdict")
        return str(verdict) if verdict is not None else None
    return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _sum_tokens(runs: list[dict[str, Any]], key: str) -> tuple[int | None, int]:
    """Sum a token field and report how many runs actually stated it."""
    values = [
        value
        for value in (
            (run.get("observations") or {}).get(key)
            for run in runs
            if isinstance(run.get("observations"), dict)
        )
        if isinstance(value, (int, float))
    ]
    if not values:
        return None, 0
    return int(sum(values)), len(values)


@dataclass(frozen=True)
class HistoryData:
    """The part of the history a report renders, read once."""

    experiments: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    plugins: list[dict[str, Any]] = field(default_factory=list)
    models: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    variants: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    snapshots: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def runs_for_experiment(self, uid: str) -> list[dict[str, Any]]:
        return [run for run in self.runs if run.get("experiment_uid") == uid]

    def runs_for_task(self, uid: str) -> list[dict[str, Any]]:
        return [run for run in self.runs if run.get("task_uid") == uid]

    def task(self, uid: str) -> dict[str, Any] | None:
        return next((row for row in self.tasks if row.get("uid") == uid), None)

    def experiment(self, uid: str) -> dict[str, Any] | None:
        return next((row for row in self.experiments if row.get("uid") == uid), None)

    def variants_for(self, uid: str) -> list[dict[str, Any]]:
        return self.variants.get(uid, [])

    def snapshots_for(self, uid: str) -> list[dict[str, Any]]:
        return self.snapshots.get(uid, [])

    def metrics_for(self, uid: str) -> list[dict[str, Any]]:
        return self.metrics.get(uid, [])


def collect_history(store: Any) -> HistoryData:
    """Read the history through the store's own reads; no SQL here."""
    experiments = store.experiments()
    return HistoryData(
        experiments=experiments,
        runs=store.runs(),
        tasks=store.tasks(),
        plugins=store.plugin_observations(),
        models=store.model_observations(),
        metrics={str(row["uid"]): store.metrics(row["uid"]) for row in experiments},
        variants={str(row["uid"]): store.variants(row["uid"]) for row in experiments},
        snapshots={str(row["uid"]): store.snapshots(row["uid"]) for row in experiments},
    )


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The same honest set of numbers for any set of runs."""
    evaluated = [run for run in runs if verdict_of(run) is not None]
    passed = [run for run in evaluated if verdict_of(run) == PASSED_VERDICT]
    durations = [value for value in (duration_seconds(run) for run in runs) if value is not None]
    tokens, token_runs = _sum_tokens(runs, "total_tokens")
    input_tokens, input_runs = _sum_tokens(runs, "input_tokens")
    output_tokens, output_runs = _sum_tokens(runs, "output_tokens")
    tool_calls, tool_call_runs = _sum_tokens(runs, "tool_call_count")
    return {
        "runs": len(runs),
        "evaluated": len(evaluated),
        "passed": len(passed),
        "not_passed": len(runs) - len(passed),
        "success_rate": _rate(len(passed), len(runs)) if evaluated else None,
        "mean_duration_seconds": _mean(durations),
        "measured_durations": len(durations),
        "total_tokens": tokens,
        "token_runs": token_runs,
        # the split the cost of a run is read from, each with the number of runs
        # that actually stated it: a run whose agent reported nothing is missing,
        # not zero
        "input_tokens": input_tokens,
        "input_token_runs": input_runs,
        "output_tokens": output_tokens,
        "output_token_runs": output_runs,
        "tool_calls": tool_calls,
        "tool_call_runs": tool_call_runs,
        "statuses": sorted({str(run.get("status")) for run in runs if run.get("status")}),
    }


def _group(runs: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        value = run.get(key)
        groups.setdefault(str(value) if value is not None else "(none)", []).append(run)
    return groups


def _by_task_attribute(
    runs: list[dict[str, Any]], tasks: list[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    labels = {row["uid"]: str(row.get(key) or "(unknown)") for row in tasks}
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        groups.setdefault(labels.get(str(run.get("task_uid")), "(unknown)"), []).append(run)
    return [
        # The key is the attribute name, so a renderer can ask for the same
        # field name it used for the column header.
        {key: label, **summarize_runs(group)} for label, group in sorted(groups.items())
    ]


def _statuses(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("verification_status"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _plugin_comparison(plugins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in plugins:
        groups.setdefault(str(row.get("plugin_id")), []).append(row)
    return [
        {
            "plugin": label,
            "runs": len(group),
            "enabled_runs": sum(1 for row in group if row.get("enabled")),
            "versions": sorted(
                {
                    str(row.get("plugin_version"))
                    for row in group
                    if row.get("plugin_version")
                }
            ),
            "verification_statuses": _statuses(group),
            "verified": all(
                row.get("verification_status") == "verified" for row in group
            ),
        }
        for label, group in sorted(groups.items())
    ]


def _model_comparison(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in models:
        key = (
            str(row.get("requested_model") or "(not stated)"),
            str(row.get("observed_model") or "(not observed)"),
        )
        groups.setdefault(key, []).append(row)
    return [
        {
            "requested": requested,
            "observed": observed,
            "runs": len(group),
            "sources": sorted(
                {
                    str(row.get("value_source"))
                    for row in group
                    if row.get("value_source")
                }
            ),
            "verification_statuses": _statuses(group),
        }
        for (requested, observed), group in sorted(groups.items())
    ]


def _values_label(values: Any) -> str:
    """A configuration as one readable string: ``knowledge_enabled=True``."""
    if isinstance(values, dict):
        if not values:
            return "(no factor: the reference configuration)"
        return ", ".join(f"{key}={value}" for key, value in sorted(values.items()))
    return str(values) if values else "(no factor: the reference configuration)"


def _rank_key(row: dict[str, Any], token_field: str = "total_tokens") -> tuple:
    """The ordering of one configuration: better first.

    Success rate is the only column that may decide on its own; time and tokens
    break a tie and never outweigh a verdict. A missing time or token total
    sorts last rather than first, because "not measured" is not "free".
    ``token_field`` is the token measure the comparison rests on: the sum for a
    pool of runs, the per-run mean when the pools have different sizes.
    """
    return (
        -(row.get("success_rate") if row.get("success_rate") is not None else -1.0),
        row.get("mean_duration_seconds")
        if row.get("mean_duration_seconds") is not None
        else float("inf"),
        row.get(token_field) if row.get(token_field) is not None else float("inf"),
    )


def _mean_per_run(total: int | None, stated: int) -> float | None:
    """A summed measure averaged over the runs that actually stated it.

    ``None`` stays ``None``: a pool whose runs reported no tokens has no mean
    either, and reading that as zero would rank an unmeasured configuration as
    free.
    """
    if total is None or not stated:
        return None
    return round(total / stated, 6)


def _place_rows(rows: list[dict[str, Any]], token_field: str = "total_tokens") -> None:
    """Put a place on every row with an evaluated run, best first, in place.

    A place is 1-based and a tie shares a place, the next one skipped, the way
    a competition ranks. A row with nothing evaluated holds no place at all: a
    run that was never scored says nothing about a configuration, and counting
    it as a failure would rank a measured one above an unmeasured one.
    """
    ranked = sorted(
        (row for row in rows if row.get("success_rate") is not None),
        key=lambda row: _rank_key(row, token_field),
    )
    for position, row in enumerate(ranked, start=1):
        previous = ranked[position - 2] if position > 1 else None
        tied = previous is not None and _rank_key(previous, token_field) == _rank_key(
            row, token_field
        )
        row["place"] = previous["place"] if tied else position
    for row in rows:
        row.setdefault("place", None)
    rows.sort(key=lambda row: (row.get("place") is None, _rank_key(row, token_field)))


def configuration_ranking(
    runs: list[dict[str, Any]],
    variants_by_experiment: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """One ranked row per configuration, pooled over every run that recorded it.

    A configuration is the factor values together with the agent and the
    runtime that executed them: the same values run by another agent, or on
    another runtime, are another configuration and hold their own row.
    Everything else pools into the one row: a second recording of the same
    experiment and the same configuration recorded in another experiment both
    add their runs to it, so its success rate is the pooled one, its times are
    averaged over all of the runs, and its tokens and tool calls are stated per
    run rather than summed, because a sum over a different number of runs is
    not a number to compare.

    The place is computed on the pooled rows: a configuration that measured
    well in two small experiments outranks one that measured well in a large
    one, and a row says which experiments it came from so the reader can weigh
    that. A run whose variant is not among the planned variants of its own
    experiment is left out: the ranking lists configurations, and an unplanned
    run states none.
    """
    values_by_variant: dict[tuple[str, str], Any] = {}
    baseline_by_variant: dict[tuple[str, str], bool] = {}
    for experiment_uid, variants in variants_by_experiment.items():
        for variant in variants:
            key = (str(experiment_uid), str(variant.get("uid")))
            values_by_variant[key] = variant.get("values")
            baseline_by_variant[key] = bool(variant.get("is_baseline"))

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for run in runs:
        key = (str(run.get("experiment_uid")), str(run.get("variant_uid")))
        if key not in values_by_variant:
            continue
        group_key = (
            _values_label(values_by_variant[key]),
            str(run.get("agent")),
            str(run.get("runtime_id")),
        )
        groups.setdefault(group_key, []).append(run)

    rows: list[dict[str, Any]] = []
    for (config, agent, runtime), group in groups.items():
        sources = {
            (str(run.get("experiment_uid")), str(run.get("variant_uid"))) for run in group
        }
        started = sorted(
            value for value in (run.get("started_at") for run in group) if value
        )
        finished = sorted(
            value for value in (run.get("finished_at") for run in group) if value
        )
        summary = summarize_runs(group)
        rows.append(
            {
                "config": config,
                "agent": agent,
                "runtime": runtime,
                "experiments": sorted({experiment for experiment, _ in sources}),
                "recordings": len(sources),
                "is_baseline": any(baseline_by_variant[source] for source in sources),
                "tasks": len(
                    {str(run.get("task_uid")) for run in group if run.get("task_uid")}
                ),
                "task_uids": sorted(
                    {str(run.get("task_uid")) for run in group if run.get("task_uid")}
                ),
                "first_started": started[0] if started else None,
                "last_finished": finished[-1] if finished else None,
                **summary,
                # the sums stay in the row for the JSON and the future pages;
                # the tables rank the per-run means, because a sum over a
                # different number of runs is not comparable
                "mean_input_tokens": _mean_per_run(
                    summary["input_tokens"], summary["input_token_runs"]
                ),
                "mean_output_tokens": _mean_per_run(
                    summary["output_tokens"], summary["output_token_runs"]
                ),
                "mean_total_tokens": _mean_per_run(
                    summary["total_tokens"], summary["token_runs"]
                ),
                "mean_tool_calls": _mean_per_run(
                    summary["tool_calls"], summary["tool_call_runs"]
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            str(row.get("first_started") or ""),
            str(row.get("config")),
            str(row.get("agent")),
            str(row.get("runtime")),
        )
    )
    _place_rows(rows, token_field="mean_total_tokens")

    baseline = next((row for row in rows if row.get("is_baseline")), None)
    for row in rows:
        row["vs_baseline"] = _vs_baseline(row, baseline, token_field="mean_total_tokens")
    return rows


def _vs_baseline(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    token_field: str = "total_tokens",
) -> str:
    """How one configuration differs from the declared baseline, in words."""
    if baseline is None or row is baseline:
        return ""
    parts: list[str] = []
    rate, base_rate = row.get("success_rate"), baseline.get("success_rate")
    if rate is not None and base_rate is not None:
        difference = round(rate - base_rate, 4)
        parts.append("success " + (f"{difference:+.0%}" if difference else "level"))
    elif rate is None or base_rate is None:
        parts.append("success not comparable")
    seconds, base_seconds = row.get("mean_duration_seconds"), baseline.get(
        "mean_duration_seconds"
    )
    if seconds is not None and base_seconds:
        ratio = seconds / base_seconds
        parts.append(f"time {ratio:.2f}x")
    else:
        parts.append("time not comparable")
    tokens, base_tokens = row.get(token_field), baseline.get(token_field)
    if tokens is not None and base_tokens:
        parts.append(f"tokens {tokens / base_tokens:.2f}x")
    return ", ".join(parts)


def unverified_configurations(data: HistoryData) -> list[dict[str, Any]]:
    """Every "not verified" the history holds, so no page can hide one."""
    findings: list[dict[str, Any]] = []
    for row in data.plugins:
        if row.get("verification_status") != "verified":
            findings.append(
                {
                    "kind": "plugin",
                    "subject": str(row.get("plugin_id")),
                    "status": str(row.get("verification_status")),
                    "run_uid": row.get("run_uid"),
                    "note": row.get("note"),
                }
            )
    for row in data.models:
        if row.get("verification_status") != "verified":
            findings.append(
                {
                    "kind": "model",
                    "subject": str(row.get("observed_model") or row.get("requested_model")),
                    "status": str(row.get("verification_status")),
                    "run_uid": row.get("run_uid"),
                    "note": row.get("note"),
                }
            )
    for experiment in data.experiments:
        if experiment.get("validity") == "invalid":
            findings.append(
                {
                    "kind": "experiment",
                    "subject": str(experiment.get("uid")),
                    "status": "invalid",
                    "run_uid": None,
                    "note": "the recorded experiment is marked invalid",
                }
            )
    return findings


def dashboard(data: HistoryData) -> dict[str, Any]:
    """Everything the front page shows, in one dictionary."""
    runs = data.runs
    stats = summarize_runs(runs)
    tokens, token_runs = _sum_tokens(runs, "total_tokens")
    input_tokens, _ = _sum_tokens(runs, "input_tokens")
    durations = [value for value in (duration_seconds(run) for run in runs) if value is not None]

    verdicts: dict[str, int] = {}
    for run in runs:
        verdict = verdict_of(run)
        if verdict is not None:
            verdicts[verdict] = verdicts.get(verdict, 0) + 1

    recent = sorted(
        data.experiments,
        key=lambda row: str(row.get("updated_at") or ""),
        reverse=True,
    )[:RECENT_LIMIT]

    return {
        **stats,
        "verdicts": verdicts,
        "experiments": len(data.experiments),
        "tasks": len(data.tasks),
        "total_tokens": tokens,
        "input_tokens": input_tokens,
        "token_runs": token_runs,
        "total_duration_seconds": round(sum(durations), 3) if durations else None,
        "cost": {
            "available": False,
            "reason": (
                "no pricing is recorded by this project: tokens are reported, "
                "a cost would be a guess"
            ),
        },
        "by_category": _by_task_attribute(runs, data.tasks, "category"),
        "by_difficulty": _by_task_attribute(runs, data.tasks, "difficulty"),
        "agents": [
            {"agent": label, **summarize_runs(group)}
            for label, group in sorted(_group(runs, "agent").items())
        ],
        "runtimes": [
            {"runtime": label, **summarize_runs(group)}
            for label, group in sorted(_group(runs, "runtime_id").items())
        ],
        "plugins": _plugin_comparison(data.plugins),
        "models": _model_comparison(data.models),
        "recent_experiments": recent,
        "unverified_configurations": unverified_configurations(data),
    }


def build_category_report(data: HistoryData, label: str) -> SubjectReport:
    """Every run of one task category, whichever experiment it came from."""
    labels = {
        str(row.get("uid")): str(row.get("category") or "(unknown)") for row in data.tasks
    }
    return _subject(
        data,
        "category",
        label,
        [run for run in data.runs if labels.get(str(run.get("task_uid"))) == label],
    )


def build_difficulty_report(data: HistoryData, label: str) -> SubjectReport:
    """Every run of one difficulty, whichever experiment it came from."""
    labels = {
        str(row.get("uid")): str(row.get("difficulty") or "(unknown)") for row in data.tasks
    }
    return _subject(
        data,
        "difficulty",
        label,
        [run for run in data.runs if labels.get(str(run.get("task_uid"))) == label],
    )


def build_verdict_report(data: HistoryData, label: str) -> SubjectReport:
    """Every evaluated run that carries one verdict.

    A verdict belongs to an evaluation, not to a run: a run that was never
    scored has no verdict, so it belongs to none of these pages rather than to
    an invented one.
    """
    return _subject(
        data,
        "verdict",
        label,
        [run for run in data.runs if verdict_of(run) == label],
    )


def build_run_report(
    data: HistoryData, run_uid: str, dataset: Any = None
) -> RunReport | None:
    """One run as it was recorded, or ``None`` when the history does not hold it."""
    run = next((row for row in data.runs if str(row.get("uid")) == str(run_uid)), None)
    if run is None:
        return None
    parameters = None
    for variant in data.variants_for(str(run.get("experiment_uid") or "")):
        if str(variant.get("uid")) == str(run.get("variant_uid")):
            parameters = variant.get("values")
            break
    task_uid = str(run.get("task_uid") or "")
    return RunReport(
        run=run,
        parameters=parameters,
        experiment=data.experiment(str(run.get("experiment_uid") or "")),
        task=data.task(task_uid) if task_uid else None,
        definition=task_definition(dataset, task_uid) if task_uid else None,
        plugin_states=[row for row in data.plugins if row.get("run_uid") == run.get("uid")],
        model_state=next(
            (row for row in data.models if row.get("run_uid") == run.get("uid")), None
        ),
        unverified=unverified_configurations(scope_to_runs(data, [run])),
    )


def scope_to_runs(data: HistoryData, runs: list[dict[str, Any]]) -> HistoryData:
    """The same history narrowed to one set of runs; used by sub-reports."""
    run_uids = {run.get("uid") for run in runs}
    experiment_uids = {run.get("experiment_uid") for run in runs}
    return HistoryData(
        experiments=[
            row for row in data.experiments if row.get("uid") in experiment_uids
        ],
        runs=list(runs),
        plugins=[row for row in data.plugins if row.get("run_uid") in run_uids],
        models=[row for row in data.models if row.get("run_uid") in run_uids],
    )


@dataclass(frozen=True)
class ExperimentReport:
    """One experiment: what it planned, what it ran, what it measured."""

    experiment: dict[str, Any]
    runs: list[dict[str, Any]]
    variants: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    unverified: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class VariantReport:
    """One planned variant: the recording it produced, and where it ranks.

    A variant is one recording of one configuration — the values, the agent and
    the runtime that ran them — and it is the unit the history records runs
    under. The ranking merged the recordings of a configuration into one row, so
    a variant page is what still shows a single recording on its own: its runs,
    its numbers, the row it was pooled into, and the other variant uids that
    carry the same values.
    """

    variant: dict[str, Any]
    experiment: dict[str, Any]
    runs: list[dict[str, Any]]
    summary: dict[str, Any] = field(default_factory=dict)
    configuration: dict[str, Any] | None = None
    siblings: list[dict[str, Any]] = field(default_factory=list)
    unverified: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TaskReport:
    """One task: every run of it, whichever experiment it came from."""

    task: dict[str, Any]
    runs: list[dict[str, Any]]
    summary: dict[str, Any] = field(default_factory=dict)
    unverified: list[dict[str, Any]] = field(default_factory=list)
    variants: list[dict[str, Any]] = field(default_factory=list)
    definition: dict[str, Any] | None = None


@dataclass(frozen=True)
class SubjectReport:
    """One subject of a comparison — an agent, a runtime, a plugin or a model.

    The runs of a subject are the interesting part of the history that no
    single experiment owns: the same agent worked several tasks under several
    configurations, and a reader who clicked on that agent wants exactly those
    runs, with the parameters each of them was executed under.
    """

    kind: str
    label: str
    runs: list[dict[str, Any]]
    summary: dict[str, Any] = field(default_factory=dict)
    variants: list[dict[str, Any]] = field(default_factory=list)
    unverified: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    experiments: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RunReport:
    """One run, on its own page.

    A run is the smallest piece of evidence this project keeps, and a reader
    sent to a single run uid wants everything that belongs to it: which
    experiment and which configuration it was, what task, what the evaluator
    said, what the agent reported, which plugins were observed next to it and
    where the raw artifacts live.
    """

    run: dict[str, Any]
    parameters: Any = None
    experiment: dict[str, Any] | None = None
    task: dict[str, Any] | None = None
    definition: dict[str, Any] | None = None
    plugin_states: list[dict[str, Any]] = field(default_factory=list)
    model_state: dict[str, Any] | None = None
    unverified: list[dict[str, Any]] = field(default_factory=list)


def task_definition(dataset: Any, uid: str) -> dict[str, Any] | None:
    """What a task asked for, read from the dataset it was run from.

    The database keeps the identity and the digest of a task, not its prose:
    the description, the constraints and the notes live in the task directory.
    A reader of a task page wants the task itself, so the definition is read
    from disk and stamped with the digest it was read at; ``digest_matches``
    says whether that definition is still the one the recorded runs were worked
    under, because a dataset edited after a run is a different task.

    ``dataset`` is any object exposing ``require(uid)``; ``None``, or a task the
    dataset does not hold, yields ``None`` and the page says so.
    """
    if dataset is None:
        return None
    try:
        loaded = dataset.require(uid)
    except Exception:  # a dataset without this task, or one that cannot be read
        return None

    task = loaded.task
    inner = task.task
    description = next(
        (
            path.read_text(encoding="utf-8")
            for path in (Path(loaded.path) / "description.md",)
            if path.is_file()
        ),
        None,
    )
    return {
        "uid": loaded.uid,
        "title": getattr(task, "title", None),
        "description": getattr(task, "description", None),
        "created_at": task.created_at.isoformat() if getattr(task, "created_at", None) else None,
        "authors": getattr(task, "authors", []) or [],
        "description_markdown": description,
        "category": task.category,
        "difficulty": task.difficulty,
        "evaluator": inner.evaluator,
        "constraints": list(inner.constraints or []),
        "notes": inner.notes,
        "timeout_seconds": inner.timeout_seconds,
        "hidden_tests": inner.hidden_tests,
        "public_tests": inner.public_tests,
        "repository": getattr(inner.repository, "source", None),
        "ref": getattr(inner.repository, "ref", None),
        "mutation": getattr(inner.mutation, "kind", None) if inner.mutation else None,
        "digest": loaded.digest,
        "path": str(loaded.path),
    }


def build_experiment_report(data: HistoryData, uid: str) -> ExperimentReport:
    runs = order_by_start(data.runs_for_experiment(uid))
    return ExperimentReport(
        experiment=data.experiment(uid) or {"uid": uid},
        runs=runs,
        variants=data.variants_for(uid),
        snapshots=data.snapshots_for(uid),
        metrics=data.metrics_for(uid),
        summary=summarize_runs(runs),
        unverified=unverified_configurations(scope_to_runs(data, runs)),
    )


def build_variant_report(
    data: HistoryData, experiment_uid: str, variant_uid: str
) -> VariantReport | None:
    """One variant of one experiment, or ``None`` when it was never planned.

    A variant uid is unique inside its experiment and says nothing outside it,
    so both uids are needed to name one. The configuration row is looked for in
    this experiment's own ranking: it is the row this recording was pooled
    into, which is what a reader who arrived from a variant uid wants to see.
    """
    variant = next(
        (
            row
            for row in data.variants_for(experiment_uid)
            if str(row.get("uid")) == str(variant_uid)
        ),
        None,
    )
    if variant is None:
        return None
    runs = order_by_start(
        [
            run
            for run in data.runs
            if str(run.get("experiment_uid")) == str(experiment_uid)
            and str(run.get("variant_uid")) == str(variant_uid)
        ]
    )
    ranked = configuration_ranking(
        data.runs_for_experiment(experiment_uid),
        {str(experiment_uid): data.variants_for(experiment_uid)},
    )
    configuration = next(
        (row for row in ranked if row.get("config") == _values_label(variant.get("values"))),
        None,
    )
    siblings = [
        {
            "uid": row.get("uid"),
            "is_baseline": bool(row.get("is_baseline")),
            **summarize_runs(
                [
                    run
                    for run in data.runs_for_experiment(experiment_uid)
                    if str(run.get("variant_uid")) == str(row.get("uid"))
                ]
            ),
        }
        for row in data.variants_for(experiment_uid)
        if _values_label(row.get("values")) == _values_label(variant.get("values"))
        and str(row.get("uid")) != str(variant_uid)
    ]
    return VariantReport(
        variant=variant,
        experiment=data.experiment(experiment_uid) or {"uid": experiment_uid},
        runs=runs,
        summary=summarize_runs(runs),
        configuration=configuration,
        siblings=siblings,
        unverified=unverified_configurations(scope_to_runs(data, runs)),
    )


def build_task_report(data: HistoryData, uid: str, dataset: Any = None) -> TaskReport:
    runs = order_by_start(data.runs_for_task(uid))
    return TaskReport(
        task=data.task(uid) or {"uid": uid},
        runs=runs,
        summary=summarize_runs(runs),
        unverified=unverified_configurations(scope_to_runs(data, runs)),
        variants=_variants_of(data, runs),
        definition=task_definition(dataset, uid),
    )


def _variants_of(data: HistoryData, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The variants named by a set of runs, in the order the experiments list them."""
    experiment_uids = {str(run.get("experiment_uid")) for run in runs}
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for experiment_uid in sorted(experiment_uids):
        for variant in data.variants_for(experiment_uid):
            uid = str(variant.get("uid"))
            if uid not in seen:
                seen.add(uid)
                collected.append(variant)
    return collected


def _subject(
    data: HistoryData,
    kind: str,
    label: str,
    runs: list[dict[str, Any]],
    observations: list[dict[str, Any]] | None = None,
) -> SubjectReport:
    ordered = order_by_start(runs)
    return SubjectReport(
        kind=kind,
        label=label,
        runs=ordered,
        summary=summarize_runs(ordered),
        variants=_variants_of(data, ordered),
        unverified=unverified_configurations(scope_to_runs(data, ordered)),
        observations=list(observations or []),
        experiments=_group_summary(data, ordered, "experiment_uid", kind="experiment"),
        tasks=_group_summary(data, ordered, "task_uid", kind="task"),
    )


def _group_summary(
    data: HistoryData,
    runs: list[dict[str, Any]],
    key: str,
    *,
    kind: str,
) -> list[dict[str, Any]]:
    """One summarised row per value of a run field, so a page can answer
    "which experiments / which tasks was this in" without another click."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        value = run.get(key)
        groups.setdefault(str(value) if value is not None else "(none)", []).append(run)
    rows: list[dict[str, Any]] = []
    for name, group in sorted(groups.items()):
        if kind == "experiment":
            detail = data.experiment(name) or {}
            rows.append(
                {
                    "uid": name,
                    "title": detail.get("title"),
                    "type": detail.get("type"),
                    **summarize_runs(group),
                }
            )
        else:
            detail = data.task(name) or {}
            rows.append(
                {
                    "uid": name,
                    "category": detail.get("category"),
                    "difficulty": detail.get("difficulty"),
                    **summarize_runs(group),
                }
            )
    return rows


def build_agent_report(data: HistoryData, label: str) -> SubjectReport:
    return _subject(
        data,
        "agent",
        label,
        [run for run in data.runs if str(run.get("agent")) == label],
    )


def build_runtime_report(data: HistoryData, label: str) -> SubjectReport:
    return _subject(
        data,
        "runtime",
        label,
        [run for run in data.runs if str(run.get("runtime_id")) == label],
    )


def build_plugin_report(data: HistoryData, label: str) -> SubjectReport:
    """A plugin and the runs it was observed in.

    A plugin is not a field of a run: it is observed next to one, and the
    observation is the only evidence that the plugin was there at all.
    """
    observations = [
        row for row in data.plugins if str(row.get("plugin_id")) == label
    ]
    run_uids = {row.get("run_uid") for row in observations}
    return _subject(
        data,
        "plugin",
        label,
        [run for run in data.runs if run.get("uid") in run_uids],
        observations,
    )


def build_model_report(data: HistoryData, label: str) -> SubjectReport:
    """A requested model and the runs that asked the router for it."""
    observations = [
        row
        for row in data.models
        if str(row.get("requested_model") or "(not stated)") == label
    ]
    return _subject(
        data,
        "model",
        label,
        [run for run in data.runs if str(run.get("requested_model") or "(not stated)") == label],
        observations,
    )

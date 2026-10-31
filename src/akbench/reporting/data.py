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
from datetime import datetime
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
    return {
        "runs": len(runs),
        "evaluated": len(evaluated),
        "passed": len(passed),
        "not_passed": len(runs) - len(passed),
        "success_rate": _rate(len(passed), len(evaluated)),
        "mean_duration_seconds": _mean(durations),
        "measured_durations": len(durations),
        "total_tokens": tokens,
        "token_runs": token_runs,
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
class TaskReport:
    """One task: every run of it, whichever experiment it came from."""

    task: dict[str, Any]
    runs: list[dict[str, Any]]
    summary: dict[str, Any] = field(default_factory=dict)
    unverified: list[dict[str, Any]] = field(default_factory=list)


def build_experiment_report(data: HistoryData, uid: str) -> ExperimentReport:
    runs = data.runs_for_experiment(uid)
    return ExperimentReport(
        experiment=data.experiment(uid) or {"uid": uid},
        runs=runs,
        variants=data.variants_for(uid),
        snapshots=data.snapshots_for(uid),
        metrics=data.metrics_for(uid),
        summary=summarize_runs(runs),
        unverified=unverified_configurations(scope_to_runs(data, runs)),
    )


def build_task_report(data: HistoryData, uid: str) -> TaskReport:
    runs = data.runs_for_task(uid)
    return TaskReport(
        task=data.task(uid) or {"uid": uid},
        runs=runs,
        summary=summarize_runs(runs),
        unverified=unverified_configurations(scope_to_runs(data, runs)),
    )

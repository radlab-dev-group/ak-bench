"""Building one experiment's export: the same facts, in three formats.

The export is a self-contained artifact of one experiment: its descriptor,
the pinned descriptors, its variants, its runs, its metrics and its
artifacts, as JSON and as CSV, with the experiment page from the report as
the HTML form. The document is screened before it is written, so the export
is safe to publish without a second pass.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from akbench.core.time import utc_now
from akbench.export.redact import redact
from akbench.reporting.data import HistoryData, build_experiment_report, duration_seconds
from akbench.reporting.render import render_experiment

FORMATS: tuple[str, ...] = ("json", "csv", "html")

_RUN_CSV_COLUMNS: tuple[str, ...] = (
    "run_uid",
    "experiment_uid",
    "variant_uid",
    "task_uid",
    "agent",
    "mode",
    "runtime_id",
    "repetition",
    "status",
    "verdict",
    "score",
    "tests_passed",
    "tests_failed",
    "tests_total",
    "exit_code",
    "failure_class",
    "error_message",
    "started_at",
    "finished_at",
    "duration_seconds",
    "input_tokens",
    "total_tokens",
    "manifest_digest",
)


@dataclass(frozen=True)
class ExportBundle:
    """The screened document of one export, with what the screen withheld."""

    experiment_uid: str
    document: dict[str, Any] = field(default_factory=dict)
    redactions: list[dict[str, int]] = field(default_factory=list)
    generated_at: str = ""


def build_export(data: HistoryData, experiment_uid: str) -> ExportBundle:
    """Gather the experiment's history and screen it for secrets."""
    report = build_experiment_report(data, experiment_uid)
    experiment = data.experiment(experiment_uid) or {}

    document: dict[str, Any] = {
        "experiment": {
            "uid": experiment_uid,
            "title": experiment.get("title"),
            "type": experiment.get("type"),
            "descriptor": experiment.get("descriptor"),
            "config_hash": experiment.get("config_hash"),
            "validity": experiment.get("validity"),
        },
        "variants": report.variants,
        "pinned_descriptors": report.snapshots,
        "runs": report.runs,
        "metrics": report.metrics,
        "summary": report.summary,
        "artifacts": [
            {
                "run_uid": run.get("uid"),
                "kind": artifact.get("kind"),
                "path": artifact.get("path"),
                "checksum": artifact.get("checksum"),
            }
            for run in report.runs
            for artifact in run.get("artifacts") or []
        ],
        "unverified_configurations": report.unverified,
        "generated_at": utc_now().isoformat(),
    }
    screened, redactions = redact(document)
    return ExportBundle(
        experiment_uid=experiment_uid,
        document=screened,
        redactions=redactions,
        generated_at=document["generated_at"],
    )


def _run_csv_row(run: dict[str, Any]) -> dict[str, Any]:
    evaluation = run.get("evaluation") if isinstance(run.get("evaluation"), dict) else {}
    observations = (
        run.get("observations") if isinstance(run.get("observations"), dict) else {}
    )
    return {
        "run_uid": run.get("uid"),
        "experiment_uid": run.get("experiment_uid"),
        "variant_uid": run.get("variant_uid"),
        "task_uid": run.get("task_uid"),
        "agent": run.get("agent"),
        "mode": run.get("mode"),
        "runtime_id": run.get("runtime_id"),
        "repetition": run.get("repetition"),
        "status": run.get("status"),
        "verdict": evaluation.get("verdict"),
        "score": evaluation.get("score"),
        "tests_passed": evaluation.get("passed"),
        "tests_failed": evaluation.get("failed"),
        "tests_total": evaluation.get("total"),
        "exit_code": run.get("exit_code"),
        "failure_class": run.get("failure_class"),
        "error_message": run.get("error_message"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "duration_seconds": duration_seconds(run),
        "input_tokens": observations.get("input_tokens"),
        "total_tokens": observations.get("total_tokens"),
        "manifest_digest": run.get("manifest_digest"),
    }


def to_json(bundle: ExportBundle) -> str:
    return json.dumps(bundle.document, indent=2, ensure_ascii=False, default=str) + "\n"


def to_csv(bundle: ExportBundle) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_RUN_CSV_COLUMNS)
    for run in bundle.document.get("runs", []):
        row = _run_csv_row(run)
        writer.writerow(["" if row[column] is None else row[column] for column in _RUN_CSV_COLUMNS])
    return buffer.getvalue()


def to_html(bundle: ExportBundle, data: HistoryData) -> str:
    report = build_experiment_report(data, bundle.experiment_uid)
    return render_experiment(
        report, generated_at=bundle.generated_at, standalone=True
    )


def write_bundle(
    bundle: ExportBundle,
    data: HistoryData,
    *,
    output_dir: Path | str,
    formats: tuple[str, ...] = FORMATS,
) -> list[Path]:
    """Write the export under ``output_dir`` and return the files written."""
    root = Path(output_dir)
    written: list[Path] = []
    for name in formats:
        if name not in FORMATS:
            raise ValueError(f"unsupported export format: {name}")
    if "json" in formats:
        target = root / f"{bundle.experiment_uid}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(to_json(bundle), encoding="utf-8")
        written.append(target)
    if "csv" in formats:
        target = root / f"{bundle.experiment_uid}.runs.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(to_csv(bundle), encoding="utf-8")
        written.append(target)
    if "html" in formats:
        target = root / f"{bundle.experiment_uid}.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(to_html(bundle, data), encoding="utf-8")
        written.append(target)
    return written

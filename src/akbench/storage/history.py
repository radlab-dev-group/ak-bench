"""Writing and reading the history of experiments (plan section 19).

The :class:`HistoryStore` is the single place that knows how a plan, a run and
its aftermath become rows. Everything else — the CLI, the orchestrator, a
future scheduler — hands it the objects it already has and gets back
identities it can refer to.

The rules that shape it:

- a row keeps the identity it was observed under (descriptor digests, config
  hashes, plugin versions), so a result stays traceable after the descriptors
  have moved on;
- a value that was never measured is stored as ``NULL``, never as zero;
- an artifact row is a pointer *plus* a checksum, because a path to a file
  that has since changed proves nothing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from akbench.core.time import utc_now
from akbench.datasets.dataset import DESCRIPTION_FILE, TASK_FILE
from akbench.storage.db import session_scope
from akbench.storage.models import (
    Agent,
    AgentObservation,
    Artifact,
    Benchmark,
    DescriptorSnapshot,
    EvaluationRecord,
    EventLog,
    Experiment,
    ExperimentMetric,
    ExperimentVariant,
    MetricRecord,
    ModelObservation,
    PluginObservation,
    Repository,
    Runtime,
    Task,
    TaskFile,
    TaskRun,
)


def _digest_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _dump(payload: Any | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def _load(text_value: str | None) -> Any | None:
    if text_value is None:
        return None
    try:
        return json.loads(text_value)
    except ValueError:
        return text_value


def _download_filename(run_uid: str, filename: str) -> str:
    """Format downloaded filename with run UID as prefix and original name as postfix."""
    if not filename:
        return ""
    if not run_uid:
        return filename
    if filename.startswith(f"{run_uid}-") or filename.startswith(f"{run_uid}_"):
        return filename
    return f"{run_uid}-{filename}"


class HistoryStore:
    """Reads and writes the experiment history of one database."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ---------------------------------------------------------------- plans

    def record_plan(
        self,
        *,
        experiment_uid: str,
        title: str | None = None,
        description: str | None = None,
        experiment_type: str | None = None,
        descriptor_id: str | None = None,
        descriptor_version: str | None = None,
        config_hash: str | None = None,
        experiment_yaml: str | None = None,
        benchmark_uid: str | None = None,
        variants: list[dict[str, Any]] | None = None,
        snapshots: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Record an experiment and its plan. Idempotent per ``experiment_uid``.

        Existing rows are updated, so re-planning an experiment does not fork
        its history: the digest changes, the row does not multiply.
        """
        with session_scope(self.engine) as session:
            now = utc_now()
            experiment = session.scalar(select(Experiment).where(Experiment.uid == experiment_uid))
            if experiment is None:
                experiment = Experiment(
                    uid=experiment_uid,
                    created_at=now,
                    updated_at=now,
                )
                session.add(experiment)
            # ``None`` is "leave what was recorded", not "clear it": a run stored
            # under a planned uid must not erase the descriptor or configuration
            # hash the plan recorded for it.
            if title is not None:
                experiment.title = title
            if description is not None:
                experiment.description = description
            if experiment_type is not None:
                experiment.experiment_type = experiment_type
            if descriptor_id is not None:
                experiment.descriptor_id = descriptor_id
            if descriptor_version is not None:
                experiment.descriptor_version = descriptor_version
            if config_hash is not None:
                experiment.config_hash = config_hash
            if experiment_yaml is not None:
                experiment.experiment_yaml = experiment_yaml
            experiment.updated_at = now

            if benchmark_uid is not None:
                self._record_benchmark(session, benchmark_uid)

            if variants is not None:
                existing = {
                    row.uid
                    for row in session.scalars(
                        select(ExperimentVariant).where(
                            ExperimentVariant.experiment_id == experiment.id
                        )
                    )
                }
                for variant in variants:
                    if variant["uid"] in existing:
                        continue
                    session.add(
                        ExperimentVariant(
                            uid=variant["uid"],
                            experiment_id=experiment.id,
                            index=int(variant.get("index", 0)),
                            values_json=_dump(variant.get("values")),
                            agent_config_json=_dump(variant.get("agent_config")),
                            environment_requests_json=_dump(variant.get("environment_requests")),
                            applies_json=_dump(variant.get("applies")),
                            config_hash=variant.get("config_hash"),
                            is_baseline=bool(variant.get("is_baseline", False)),
                            created_at=now,
                            updated_at=now,
                        )
                    )

            if snapshots is not None:
                for snapshot in snapshots:
                    self._record_snapshot(session, experiment.id, snapshot)

            session.flush()
            return {"uid": experiment_uid, "experiment_id": experiment.id}

    # ----------------------------------------------------------------- runs

    def record_run(
        self,
        record: dict[str, Any],
        *,
        experiment_uid: str | None = None,
        variant_uid: str | None = None,
        task: Any | None = None,
        observed_model: dict[str, Any] | None = None,
        repetition: int | None = None,
        agent_descriptor: Any | None = None,
        runtime_descriptor: Any | None = None,
    ) -> dict[str, Any]:
        """Store one run record and its attached observations.

        ``record`` is the shape the orchestrator writes to
        ``run_record.json``. ``task`` is the :class:`LoadedTask` of the run;
        when it is given the repository and task rows are kept in sync, and a
        run whose task is unknown is stored with the link ``NULL`` and an
        event saying so, rather than invented.
        """
        with session_scope(self.engine) as session:
            now = utc_now()
            run_uid = str(record["run_uid"])
            experiment_id: int | None = None
            if experiment_uid is not None:
                experiment = session.scalar(
                    select(Experiment).where(Experiment.uid == experiment_uid)
                )
                experiment_id = experiment.id if experiment is not None else None
                if experiment_id is None:
                    self._record_experiment(session, experiment_uid)
                    experiment = session.scalar(
                        select(Experiment).where(Experiment.uid == experiment_uid)
                    )
                    experiment_id = experiment.id

            if task is not None:
                self._record_task(session, task)
            if agent_descriptor is not None:
                # A run records the agent it used at the version it observed
                # (codex-cli 0.166.0), not only the descriptor's declared
                # version, so the row the run names is the row the catalog has.
                self._record_component(
                    session, Agent, agent_descriptor, "agent",
                    record.get("agent_version"),
                )
            if runtime_descriptor is not None:
                self._record_component(
                    session, Runtime, runtime_descriptor, "runtime",
                )

            run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
            if run is None:
                run = TaskRun(uid=run_uid, created_at=now, updated_at=now)
                session.add(run)
            run.experiment_id = experiment_id
            run.variant_uid = variant_uid
            declared_task = record.get("task_uid")
            known = (
                session.scalar(select(Task).where(Task.uid == declared_task))
                if declared_task
                else None
            )
            run.task_uid = known.uid if known is not None else None
            run.agent_id = record.get("agent_id")
            run.agent_version = record.get("agent_version")
            run.session_id = record.get("session_id")
            run.workspace_path = record.get("workspace_path")
            run.status = str(record.get("state", "pending"))
            run.failure_class = record.get("failure_class")
            run.error_message = record.get("error_message")
            run.exit_code = record.get("exit_code")
            run.mode = record.get("mode")
            run.runtime_id = record.get("runtime_id")
            run.manifest_digest = record.get("manifest_digest")
            if repetition is not None:
                run.repetition = int(repetition)
            run.started_at = _parse_time(record.get("started_at"))
            run.finished_at = _parse_time(record.get("finished_at"))
            run.updated_at = now
            session.flush()

            if declared_task is not None and known is None:
                self._record_event(
                    session,
                    run_id=run.id,
                    experiment_id=experiment_id,
                    event_type="task_unrecorded",
                    level="warning",
                    message=(
                        f"run cites task {declared_task}, which is not in the history; "
                        "the link is left empty rather than invented"
                    ),
                )
            self._record_lifecycle(session, run, record)
            self._record_evaluation(session, run, record.get("evaluation"))
            self._record_agent_observations(session, run, record)
            # The requested model is a fact of the run (declared by the
            # experiment); the observed model is what the agent reported. When
            # the caller did not pass an explicit payload, the record itself is
            # the source, so neither side of the comparison is lost.
            if observed_model is not None:
                payload = dict(observed_model)
                payload.setdefault("requested_model", record.get("requested_model"))
                self._record_model_observation(session, run, payload)
            else:
                derived = HistoryStore._model_payload(record)
                if derived["requested_model"] or derived["observed_model"]:
                    self._record_model_observation(session, run, derived)

            session.flush()
            return {"run_uid": run_uid, "run_id": run.id, "status": run.status}

    # -------------------------------------------------------------- plugins

    def record_plugin_observations(
        self, run_uid: str, reports: list[dict[str, Any]]
    ) -> int:
        """Store the plugin state of one run (plan 10.2).

        ``reports`` are the ``as_dict()`` payloads of :class:`PluginReport`.
        Re-calling for the same run replaces its observations, because the
        state of a plugin for a run is one fact, not a log.
        """
        with session_scope(self.engine) as session:
            run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
            if run is None:
                raise KeyError(f"unknown run: {run_uid}")
            now = utc_now()
            for report in session.scalars(
                select(PluginObservation).where(PluginObservation.run_id == run.id)
            ):
                session.delete(report)
            stored = 0
            for report in reports:
                session.add(
                    PluginObservation(
                        run_id=run.id,
                        plugin_id=str(report.get("plugin_id", "")),
                        plugin_version=report.get("plugin_version"),
                        descriptor_digest=report.get("digest"),
                        enabled=bool(report.get("enabled", False)),
                        verification_status=str(
                            (report.get("state") or {}).get("verification_status", "unverified")
                        ),
                        state_json=_dump(report.get("state")),
                        note=report.get("note"),
                        created_at=now,
                        updated_at=now,
                    )
                )
                stored += 1
            session.flush()
            return stored

    # ------------------------------------------------------------ artifacts

    def register_artifacts(
        self,
        run_uid: str,
        paths: list[str | Path],
        *,
        store_data: bool = True,
    ) -> list[dict[str, Any]]:
        """Checksum and register the files a run left behind.

        A missing file is reported in the result, not an error: a run may
        legitimately have produced fewer artifacts than another, and a report
        must be able to tell which ones are absent.
        """
        with session_scope(self.engine) as session:
            run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
            if run is None:
                raise KeyError(f"unknown run: {run_uid}")
            now = utc_now()
            results: list[dict[str, Any]] = []
            for raw in paths:
                path = Path(raw)
                info = {
                    "kind": _artifact_kind(path.name),
                    "path": str(path),
                    "present": path.is_file(),
                }
                if not info["present"]:
                    results.append(info)
                    continue
                data = path.read_bytes()
                checksum = _digest_bytes(data)
                size_bytes = len(data)
                content_type = _content_type(path.name)
                existing = session.scalar(
                    select(Artifact).where(
                        Artifact.run_id == run.id,
                        Artifact.path == str(path),
                        Artifact.kind == info["kind"],
                    )
                )
                if existing is not None:
                    existing.checksum = checksum
                    existing.size_bytes = size_bytes
                    existing.content_type = content_type
                    existing.data = data if store_data else None
                    existing.updated_at = now
                else:
                    session.add(
                        Artifact(
                            run_id=run.id,
                            kind=info["kind"],
                            path=str(path),
                            checksum=checksum,
                            size_bytes=size_bytes,
                            content_type=content_type,
                            data=data if store_data else None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                info["checksum"] = checksum
                info["size_bytes"] = size_bytes
                results.append(info)
            session.flush()
            return results

    def get_artifact_payload(self, run_uid: str, filename_or_path: str) -> bytes | None:
        """Read the binary payload of an artifact from the database."""
        with session_scope(self.engine) as session:
            run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
            if run is None:
                return None
            target_name = filename_or_path
            if target_name.startswith(f"{run_uid}-"):
                target_name = target_name[len(run_uid) + 1 :]
            elif target_name.startswith(f"{run_uid}_"):
                target_name = target_name[len(run_uid) + 1 :]
            artifact = session.scalar(
                select(Artifact).where(
                    Artifact.run_id == run.id,
                    (Artifact.path == filename_or_path)
                    | (Artifact.path == target_name)
                    | (Artifact.path.like(f"%/{filename_or_path}"))
                    | (Artifact.path.like(f"%/{target_name}"))
                    | (Artifact.kind == filename_or_path)
                    | (Artifact.kind == target_name),
                )
            )
            return artifact.data if artifact else None

    def export_artifacts(
        self,
        run_uid: str,
        target_dir: Path | str,
        *,
        prefix_run_uid: bool = False,
    ) -> list[Path]:
        """Export all registered artifacts for a run into target_dir."""
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        exported: list[Path] = []
        with session_scope(self.engine) as session:
            run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
            if run is None:
                return exported
            artifacts = session.scalars(select(Artifact).where(Artifact.run_id == run.id)).all()
            for artifact in artifacts:
                base_filename = Path(artifact.path).name
                filename = (
                    _download_filename(run_uid, base_filename)
                    if prefix_run_uid
                    else base_filename
                )
                dest = target / filename
                if artifact.data is not None:
                    dest.write_bytes(artifact.data)
                    exported.append(dest)
                elif Path(artifact.path).is_file():
                    dest.write_bytes(Path(artifact.path).read_bytes())
                    exported.append(dest)
        return exported

    def verify_artifacts(self, run_uid: str) -> list[dict[str, Any]]:
        """Re-checksum a run's artifacts against what was registered."""
        with session_scope(self.engine) as session:
            run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
            if run is None:
                raise KeyError(f"unknown run: {run_uid}")
            results: list[dict[str, Any]] = []
            for artifact in session.scalars(
                select(Artifact).where(Artifact.run_id == run.id)
            ):
                path = Path(artifact.path)
                if not path.is_file():
                    results.append(
                        {
                            "kind": artifact.kind,
                            "path": artifact.path,
                            "ok": False,
                            "reason": "missing",
                        }
                    )
                    continue
                checksum = _digest_bytes(path.read_bytes())
                results.append(
                    {
                        "kind": artifact.kind,
                        "path": artifact.path,
                        "ok": checksum == artifact.checksum,
                        "reason": None if checksum == artifact.checksum else "checksum mismatch",
                    }
                )
            return results

    # -------------------------------------------------------------- metrics

    def record_metric_catalog(self, catalog: dict[str, dict[str, Any]]) -> int:
        """Upsert the metric catalog, as observed at this moment."""
        with session_scope(self.engine) as session:
            now = utc_now()
            for metric_id, body in catalog.items():
                metric = session.scalar(
                    select(MetricRecord).where(
                        MetricRecord.metric_id == metric_id,
                        MetricRecord.version == str(body.get("version", "1.0.0")),
                    )
                )
                if metric is None:
                    metric = MetricRecord(
                        metric_id=metric_id,
                        version=str(body.get("version", "1.0.0")),
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(metric)
                metric.title = body.get("title")
                metric.metric_group = str(body.get("group", "quality"))
                metric.unit = body.get("unit")
                metric.direction = body.get("direction")
                metric.availability = str(body.get("availability", "computed"))
                metric.unavailable_reason = body.get("unavailable_reason")
                metric.digest = body.get("digest")
                metric.updated_at = now
            session.flush()
            return len(catalog)

    def record_experiment_metrics(
        self,
        experiment_uid: str,
        aggregates: dict[str, dict[str, Any]],
        *,
        variant_uid: str = "*",
    ) -> int:
        """Store (or replace) the aggregates of one experiment."""
        with session_scope(self.engine) as session:
            experiment = session.scalar(
                select(Experiment).where(Experiment.uid == experiment_uid)
            )
            if experiment is None:
                raise KeyError(f"unknown experiment: {experiment_uid}")
            now = utc_now()
            for row in session.scalars(
                select(ExperimentMetric).where(
                    ExperimentMetric.experiment_id == experiment.id,
                    ExperimentMetric.variant_uid == variant_uid,
                )
            ):
                session.delete(row)
            # The deletes go first: a re-aggregated metric reuses the same
            # (experiment, variant, metric) identity, so the rows it replaces
            # must be gone before the new ones are inserted.
            session.flush()
            for metric_id, body in aggregates.items():
                session.add(
                    ExperimentMetric(
                        experiment_id=experiment.id,
                        variant_uid=variant_uid,
                        metric_id=metric_id,
                        metric_group=body.get("group"),
                        unit=body.get("unit"),
                        runs=int(body.get("runs", 0)),
                        measured=int(body.get("measured", 0)),
                        availability=body.get("availability"),
                        mean=body.get("mean"),
                        minimum=body.get("minimum"),
                        maximum=body.get("maximum"),
                        deviation=body.get("deviation"),
                        unavailable_reason=body.get("unavailable_reason"),
                        computed_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.flush()
            return len(aggregates)

    # ---------------------------------------------------------------- events

    def record_events(
        self,
        events: list[dict[str, Any]],
        *,
        run_uid: str | None = None,
        experiment_uid: str | None = None,
    ) -> int:
        with session_scope(self.engine) as session:
            run_id = experiment_id = None
            if run_uid is not None:
                run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
                run_id = run.id if run else None
            if experiment_uid is not None:
                experiment = session.scalar(
                    select(Experiment).where(Experiment.uid == experiment_uid)
                )
                experiment_id = experiment.id if experiment else None
            now = utc_now()
            for event in events:
                session.add(
                    EventLog(
                        run_id=run_id,
                        experiment_id=experiment_id,
                        occurred_at=(
                    _parse_time(event.get("at") or event.get("occurred_at")) or now
                ),
                        event_type=str(event.get("event_type", event.get("state", "event"))),
                        level=str(event.get("level", "info")),
                        message=event.get("message"),
                        details_json=_dump(event.get("details")),
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.flush()
            return len(events)

    # ---------------------------------------------------------------- reads

    def experiments(self) -> list[dict[str, Any]]:
        with session_scope(self.engine) as session:
            rows = session.scalars(select(Experiment)).all()
            return [self._experiment_dict(session, row) for row in rows]

    def runs(self, experiment_uid: str | None = None) -> list[dict[str, Any]]:
        with session_scope(self.engine) as session:
            statement = select(TaskRun)
            if experiment_uid is not None:
                experiment = session.scalar(
                    select(Experiment).where(Experiment.uid == experiment_uid)
                )
                if experiment is None:
                    return []
                statement = statement.where(TaskRun.experiment_id == experiment.id)
            rows = session.scalars(statement.order_by(TaskRun.started_at)).all()
            return [self._run_dict(session, row) for row in rows]

    def run(self, run_uid: str) -> dict[str, Any] | None:
        with session_scope(self.engine) as session:
            row = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
            return self._run_dict(session, row) if row else None

    def tasks(self) -> list[dict[str, Any]]:
        """Every recorded task with how often it was run."""
        with session_scope(self.engine) as session:
            rows = session.scalars(select(Task).order_by(Task.uid)).all()
            runs = session.scalars(select(TaskRun)).all()
            by_task: dict[str, int] = {}
            for run in runs:
                if run.task_uid:
                    by_task[run.task_uid] = by_task.get(run.task_uid, 0) + 1
            return [
                {
                    "uid": row.uid,
                    "id": row.task_id,
                    "version": row.version,
                    "title": row.title,
                    "category": row.category,
                    "difficulty": row.difficulty,
                    "evaluator": row.evaluator,
                    "repository_uid": row.repository_uid,
                    "base_commit": row.base_commit,
                    "snapshot_digest": row.snapshot_digest,
                    "created_at": row.task_created_at.isoformat() if row.task_created_at else None,
                    "authors": _load(row.authors_json) or [],
                    "description": row.description,
                    "task_yaml": row.task_yaml,
                    "description_md": row.description_md,
                    "runs": by_task.get(row.uid, 0),
                }
                for row in rows
            ]

    def task_files(self, task_uid: str | None = None) -> list[dict[str, Any]]:
        """The recorded code of a task, or of every task, sorted by path.

        Content is left out: a tree of files is a list of names, sizes and
        kinds, and the text of one file is read when it is opened. A task with
        no recorded files is not an error — it predates the recording, or the
        dataset was not on disk when it was recorded.
        """
        with session_scope(self.engine) as session:
            statement = (
                select(Task, TaskFile)
                .join(TaskFile, TaskFile.task_id == Task.id)
                .order_by(TaskFile.kind, TaskFile.path)
            )
            if task_uid is not None:
                statement = statement.where(Task.uid == task_uid)
            rows = session.execute(statement).all()
            return [
                {
                    "task_uid": task.uid,
                    "path": row.path,
                    "kind": row.kind,
                    "size_bytes": row.size_bytes,
                    "digest": row.digest,
                }
                for task, row in rows
            ]

    def task_file(self, task_uid: str, path: str) -> dict[str, Any] | None:
        """One recorded file with its content, or ``None`` when it was not stored."""
        with session_scope(self.engine) as session:
            row = session.execute(
                select(TaskFile)
                .join(Task, Task.id == TaskFile.task_id)
                .where(Task.uid == task_uid, TaskFile.path == path)
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "task_uid": task_uid,
                "path": row.path,
                "kind": row.kind,
                "content": row.content,
                "size_bytes": row.size_bytes,
                "digest": row.digest,
            }

    def plugin_observations(
        self, run_uid: str | None = None
    ) -> list[dict[str, Any]]:
        """Plugin states, one row per (run, plugin), for the plugin pages."""
        with session_scope(self.engine) as session:
            statement = select(PluginObservation).order_by(
                PluginObservation.run_id, PluginObservation.plugin_id
            )
            if run_uid is not None:
                run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
                if run is None:
                    return []
                statement = statement.where(PluginObservation.run_id == run.id)
            runs = {row.id: row.uid for row in session.scalars(select(TaskRun)).all()}
            return [
                {
                    "run_uid": runs.get(row.run_id),
                    "plugin_id": row.plugin_id,
                    "plugin_version": row.plugin_version,
                    "descriptor_digest": row.descriptor_digest,
                    "enabled": row.enabled,
                    "verification_status": row.verification_status,
                    "note": row.note,
                }
                for row in session.scalars(statement).all()
            ]

    def model_observations(self) -> list[dict[str, Any]]:
        """Requested versus observed model, one row per run that reported one."""
        with session_scope(self.engine) as session:
            runs = {row.id: row.uid for row in session.scalars(select(TaskRun)).all()}
            rows = session.scalars(select(ModelObservation).order_by(ModelObservation.run_id)).all()
            return [
                {
                    "run_uid": runs.get(row.run_id),
                    "requested_model": row.requested_model,
                    "observed_model": row.observed_model,
                    "value_source": row.value_source,
                    "verification_status": row.verification_status,
                    "note": row.note,
                }
                for row in rows
            ]

    def variants(self, experiment_uid: str) -> list[dict[str, Any]]:
        """The variants of one experiment, in matrix order."""
        with session_scope(self.engine) as session:
            experiment = session.scalar(
                select(Experiment).where(Experiment.uid == experiment_uid)
            )
            if experiment is None:
                return []
            rows = session.scalars(
                select(ExperimentVariant)
                .where(ExperimentVariant.experiment_id == experiment.id)
                .order_by(ExperimentVariant.index, ExperimentVariant.uid)
            ).all()
            return [
                {
                    "uid": row.uid,
                    "index": row.index,
                    "values": _load(row.values_json),
                    "agent_config": _load(row.agent_config_json),
                    "environment_requests": _load(row.environment_requests_json),
                    "applies": _load(row.applies_json),
                    "config_hash": row.config_hash,
                    "is_baseline": row.is_baseline,
                }
                for row in rows
            ]

    def snapshots(self, experiment_uid: str) -> list[dict[str, Any]]:
        """The descriptors a plan pinned, with the payload as it was then."""
        with session_scope(self.engine) as session:
            experiment = session.scalar(
                select(Experiment).where(Experiment.uid == experiment_uid)
            )
            if experiment is None:
                return []
            rows = session.scalars(
                select(DescriptorSnapshot)
                .where(DescriptorSnapshot.experiment_id == experiment.id)
                .order_by(DescriptorSnapshot.kind, DescriptorSnapshot.descriptor_id)
            ).all()
            return [
                {
                    "kind": row.kind,
                    "id": row.descriptor_id,
                    "version": row.version,
                    "digest": row.digest,
                    "source": row.source,
                    "payload": _load(row.payload_json),
                }
                for row in rows
            ]

    def metrics(self, experiment_uid: str) -> list[dict[str, Any]]:
        with session_scope(self.engine) as session:
            experiment = session.scalar(
                select(Experiment).where(Experiment.uid == experiment_uid)
            )
            if experiment is None:
                return []
            rows = session.scalars(
                select(ExperimentMetric).where(
                    ExperimentMetric.experiment_id == experiment.id
                )
            ).all()
            return [self._metric_dict(row) for row in rows]

    def events(self, run_uid: str | None = None) -> list[dict[str, Any]]:
        with session_scope(self.engine) as session:
            statement = select(EventLog).order_by(EventLog.occurred_at, EventLog.id)
            if run_uid is not None:
                run = session.scalar(select(TaskRun).where(TaskRun.uid == run_uid))
                if run is None:
                    return []
                statement = statement.where(EventLog.run_id == run.id)
            return [
                {
                    "at": row.occurred_at.isoformat() if row.occurred_at else None,
                    "event_type": row.event_type,
                    "level": row.level,
                    "message": row.message,
                    "details": _load(row.details_json),
                    "run_uid": None,
                    "experiment_uid": None,
                }
                for row in session.scalars(statement).all()
            ]

    # ------------------------------------------------------------ internals

    def _record_benchmark(self, session: Session, uid: str) -> None:
        benchmark = session.scalar(select(Benchmark).where(Benchmark.uid == uid))
        if benchmark is None:
            session.add(
                Benchmark(
                    uid=uid,
                    name=uid,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )

    def _record_experiment(self, session: Session, uid: str) -> None:
        if session.scalar(select(Experiment).where(Experiment.uid == uid)) is None:
            session.add(Experiment(uid=uid, created_at=utc_now(), updated_at=utc_now()))
            session.flush()

    def _record_task(self, session: Session, loaded: Any) -> None:
        now = utc_now()
        repository_uid: str | None = None
        repository = getattr(loaded.task.task.repository, "source", None)
        if repository:
            repo_row = session.scalar(
                select(Repository).where(Repository.source == repository)
            )
            if repo_row is None:
                repo_row = Repository(
                    uid=f"repo-{hashlib.sha256(repository.encode()).hexdigest()[:16]}",
                    source=repository,
                    default_ref=getattr(loaded.task.task.repository, "ref", None),
                    created_at=now,
                    updated_at=now,
                )
                session.add(repo_row)
                session.flush()
            repository_uid = repo_row.uid

        task_row = session.scalar(select(Task).where(Task.uid == loaded.uid))
        task_created_at = getattr(loaded.task, "created_at", None)
        if isinstance(task_created_at, str):
            task_created_at = _parse_time(task_created_at)

        authors = getattr(loaded.task, "authors", None)
        authors_json = _dump(authors) if authors else None

        # The prose belongs to the task itself: the title, the one-line
        # description, the descriptor as written and the full description.md.
        # A reader of the history should see what a run was about without the
        # dataset checkout, so it is recorded, not re-derived.
        title = getattr(loaded.task, "title", None)
        description = getattr(loaded.task, "description", None)
        task_yaml, description_md = _task_texts(loaded)

        if task_row is None:
            task_row = Task(
                uid=loaded.uid,
                task_id=str(loaded.task.id),
                version=str(loaded.task.version),
                title=title,
                category=str(loaded.task.category),
                difficulty=str(loaded.task.difficulty),
                evaluator=str(loaded.task.evaluator),
                snapshot_digest=str(loaded.digest),
                task_created_at=task_created_at,
                authors_json=authors_json,
                description=description,
                task_yaml=task_yaml,
                description_md=description_md,
                created_at=now,
                updated_at=now,
            )
            session.add(task_row)
        else:
            if task_created_at is not None:
                task_row.task_created_at = task_created_at
            if authors_json is not None:
                task_row.authors_json = authors_json
            if title is not None:
                task_row.title = title
            if description is not None:
                task_row.description = description
            if task_yaml is not None:
                task_row.task_yaml = task_yaml
            if description_md is not None:
                task_row.description_md = description_md
        task_row.repository_uid = repository_uid
        task_row.base_commit = getattr(loaded.task.task.repository, "ref", None)
        task_row.updated_at = now
        session.flush()
        self._record_task_files(session, task_row, loaded)

    def _record_task_files(self, session: Session, task_row: Task, loaded: Any) -> None:
        """Store the task's code, not only its prose, next to the task row.

        The repository a run was worked in, the hidden and public tests that
        grade it, and the mutation patch that planted the defect are recorded
        file by file, so a history read without the dataset checkout can still
        show the exact code a recorded run was handed. A loaded task that did
        not come from a directory (a test stub) yields no files and changes
        nothing: there is no code to read, and guessing would fabricate it.
        """
        _store_task_files(session, task_row.id, collect_task_files(loaded))

    def record_task_files(self, loaded: Any) -> int:
        """Store the code of a task found on disk, returning how many files changed.

        The write path for ``scripts/update_task_info.py``: a history that
        predates the recording gets its files from the dataset checkout without
        waiting for a run. A task with no row was never recorded, and its code
        is not this history's to claim.
        """
        uid = getattr(loaded, "uid", None)
        collected = collect_task_files(loaded)
        if not uid or not collected:
            return 0
        with session_scope(self.engine) as session:
            task_row = session.scalar(select(Task).where(Task.uid == uid))
            if task_row is None:
                return 0
            recorded = {
                row.path: row.digest
                for row in session.scalars(
                    select(TaskFile).where(TaskFile.task_id == task_row.id)
                ).all()
            }
            _store_task_files(session, task_row.id, collected)
            return sum(
                1
                for path, _kind, _content, _size, digest in collected
                if recorded.get(path) != digest
            )

    def _record_component(
        self,
        session: Session,
        model: Any,
        descriptor: Any,
        kind: str,
        observed_version: Any = None,
    ) -> None:
        """Store an agent or runtime descriptor, keyed by (id, version).

        ``descriptor`` is the validated descriptor model or a mapping with the
        same fields; ``*_yaml`` carries the file it was written in. Re-recording
        updates the row — a descriptor that gained a note is still the same
        component — and a descriptor with no id is not a component at all, so
        it is skipped rather than guessed at.
        """
        def stated(name: str, target: Any = None) -> Any:
            """Read ``name`` from a mapping or an attribute, whichever it is."""
            subject = descriptor if target is None else target
            if isinstance(subject, dict):
                return subject.get(name)
            return getattr(subject, name, None)

        identifier = stated("id")
        if not identifier:
            return
        # The version a run names is what it observed; the descriptor's own
        # version is a fallback only when the run recorded none.
        version = str(observed_version or stated("version") or "")
        title = stated("title")
        description = stated("description")
        document = stated("descriptor_yaml")

        row = session.scalar(
            select(model).where(
                getattr(model, f"{kind}_id") == str(identifier),
                model.version == version,
            )
        )
        now = utc_now()
        if row is None:
            row = model(
                **{
                    f"{kind}_id": str(identifier),
                    "version": version,
                    "title": title,
                    "description": description,
                    f"{kind}_yaml": document,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            session.add(row)
        else:
            if title:
                row.title = title
            if description:
                row.description = description
            if document:
                setattr(row, f"{kind}_yaml", document)
            row.updated_at = now
        session.flush()

    def agents(self) -> list[dict[str, Any]]:
        """Every recorded agent version, newest first inside its id."""
        with session_scope(self.engine) as session:
            rows = session.scalars(select(Agent).order_by(Agent.agent_id, Agent.version)).all()
            return [
                {
                    "id": row.agent_id,
                    "version": row.version,
                    "uid": f"{row.agent_id}@{row.version}",
                    "title": row.title,
                    "description": row.description,
                    "agent_yaml": row.agent_yaml,
                }
                for row in rows
            ]

    def runtimes(self) -> list[dict[str, Any]]:
        """Every recorded runtime version, newest first inside its id."""
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(Runtime).order_by(Runtime.runtime_id, Runtime.version)
            ).all()
            return [
                {
                    "id": row.runtime_id,
                    "version": row.version,
                    "uid": f"{row.runtime_id}@{row.version}",
                    "title": row.title,
                    "description": row.description,
                    "runtime_yaml": row.runtime_yaml,
                }
                for row in rows
            ]

    def _record_snapshot(
        self, session: Session, experiment_id: int | None, payload: dict[str, Any]
    ) -> None:
        now = utc_now()
        existing = session.scalar(
            select(DescriptorSnapshot).where(
                DescriptorSnapshot.experiment_id == experiment_id,
                DescriptorSnapshot.kind == str(payload["kind"]),
                DescriptorSnapshot.descriptor_id == str(payload["id"]),
                DescriptorSnapshot.version == str(payload["version"]),
            )
        )
        if existing is None:
            existing = DescriptorSnapshot(
                experiment_id=experiment_id,
                kind=str(payload["kind"]),
                descriptor_id=str(payload["id"]),
                version=str(payload["version"]),
                created_at=now,
                updated_at=now,
            )
            session.add(existing)
        existing.digest = str(payload.get("digest", ""))
        existing.payload_json = _dump(payload.get("payload"))
        existing.source = payload.get("source")
        existing.updated_at = now
        session.flush()

    def _record_event(
        self,
        session: Session,
        *,
        run_id: int | None,
        experiment_id: int | None,
        event_type: str,
        message: str,
        level: str = "info",
    ) -> None:
        now = utc_now()
        session.add(
            EventLog(
                run_id=run_id,
                experiment_id=experiment_id,
                occurred_at=now,
                event_type=event_type,
                level=level,
                message=message,
                created_at=now,
                updated_at=now,
            )
        )

    def _record_lifecycle(self, session: Session, run: TaskRun, record: dict[str, Any]) -> None:
        history = record.get("history") or []
        if not history:
            return
        now = utc_now()
        for event in history:
            session.add(
                EventLog(
                    run_id=run.id,
                    occurred_at=_parse_time(event.get("at")) or now,
                    event_type=str(event.get("state", "state_change")),
                    level="info",
                    message=event.get("note"),
                    created_at=now,
                    updated_at=now,
                )
            )

    def _record_evaluation(self, session: Session, run: TaskRun, evaluation: Any) -> None:
        if not isinstance(evaluation, dict):
            return
        now = utc_now()
        for row in session.scalars(
            select(EvaluationRecord).where(EvaluationRecord.run_id == run.id)
        ):
            session.delete(row)
        if not evaluation:
            return
        session.add(
            EvaluationRecord(
                run_id=run.id,
                evaluator_id=str(evaluation.get("evaluator_id", "")),
                evaluator_version=evaluation.get("evaluator_version"),
                verdict=str(evaluation.get("verdict", "")),
                score=evaluation.get("score"),
                passed=evaluation.get("passed"),
                failed=evaluation.get("failed"),
                skipped=evaluation.get("skipped"),
                total=evaluation.get("total"),
                duration_seconds=evaluation.get("duration_seconds"),
                details_json=_dump(evaluation.get("details")),
                artifacts_json=_dump(evaluation.get("artifacts")),
                created_at=now,
                updated_at=now,
            )
        )

    def _record_agent_observations(
        self, session: Session, run: TaskRun, record: dict[str, Any]
    ) -> None:
        observations = record.get("observations")
        if not isinstance(observations, dict):
            return
        now = utc_now()
        usage = observations.get("token_usage")
        if not isinstance(usage, dict):
            usage = {}
        tool_names = observations.get("tool_names") or {}
        tool_call_count = observations.get("tool_call_count")
        if tool_call_count is None and isinstance(tool_names, dict):
            tool_call_count = sum(v for v in tool_names.values() if isinstance(v, int))

        def _field(name: str):
            """A flat field the agent stated wins; the nested block is the fallback."""
            value = observations.get(name)
            if value is None:
                value = usage.get(name)
            return value if isinstance(value, (int, float)) else None

        for row in session.scalars(
            select(AgentObservation).where(AgentObservation.run_id == run.id)
        ):
            session.delete(row)
        session.add(
            AgentObservation(
                run_id=run.id,
                session_id=observations.get("session_id") or record.get("session_id"),
                agent_status=record.get("agent_status"),
                tool_call_count=tool_call_count,
                input_tokens=_field("input_tokens"),
                cached_input_tokens=_field("cached_input_tokens"),
                output_tokens=_field("output_tokens"),
                reasoning_output_tokens=_field("reasoning_output_tokens"),
                total_tokens=_field("total_tokens"),
                observations_json=_dump(observations),
                created_at=now,
                updated_at=now,
            )
        )

    @staticmethod
    def _model_payload(record: dict[str, Any]) -> dict[str, Any]:
        """What the run says about the model it was served by, and its trust.

        Three kinds of evidence, in descending strength:

        1. the log of the instance this run started, which names the model each
           request was forwarded to — the only evidence that attributes a
           request to a run, so the only one that can verify the pairing;
        2. the inventory the instance serves, which says what it *can* serve
           and never which model served this run;
        3. what the agent reported, which repeats the request rather than
           confirming it.

        The status says which of these the row rests on; nothing here upgrades
        a weaker kind of evidence into the claim of a stronger one.
        """
        observations = record.get("observations")
        observed = (
            observations.get("observed_model") if isinstance(observations, dict) else None
        )
        requested = record.get("requested_model")
        payload = {
            "requested_model": requested,
            "observed_model": observed,
            "value_source": "agent_reported" if observed else None,
            "verification_status": "unverified",
            "note": None,
        }
        evidence = record.get("model_evidence")
        if isinstance(evidence, dict) and evidence.get("available"):
            return _verified_by_log(payload, requested, evidence)
        if record.get("served_models") is not None:
            payload["note"] = _inventory_note(requested, record.get("served_models"))
        elif isinstance(evidence, dict) and evidence.get("note"):
            payload["note"] = str(evidence["note"])
        return payload

    def _record_model_observation(
        self, session: Session, run: TaskRun, payload: dict[str, Any]
    ) -> None:
        now = utc_now()
        for row in session.scalars(
            select(ModelObservation).where(ModelObservation.run_id == run.id)
        ):
            session.delete(row)
        session.add(
            ModelObservation(
                run_id=run.id,
                requested_model=payload.get("requested_model"),
                observed_model=payload.get("observed_model"),
                value_source=payload.get("value_source"),
                verification_status=str(payload.get("verification_status", "unverified")),
                note=payload.get("note"),
                created_at=now,
                updated_at=now,
            )
        )

    def _experiment_dict(self, session: Session, row: Experiment) -> dict[str, Any]:
        runs = session.scalars(select(TaskRun).where(TaskRun.experiment_id == row.id)).all()
        verdicts: dict[str, int] = {}
        for run in runs:
            verdict = session.scalar(
                select(EvaluationRecord.verdict).where(EvaluationRecord.run_id == run.id)
            )
            if verdict:
                verdicts[verdict] = verdicts.get(verdict, 0) + 1
        return {
            "uid": row.uid,
            "title": row.title,
            "description": row.description,
            "type": row.experiment_type,
            "descriptor": f"{row.descriptor_id}@{row.descriptor_version}"
            if row.descriptor_id
            else None,
            "validity": row.validity_status,
            "config_hash": row.config_hash,
            "experiment_yaml": row.experiment_yaml,
            "runs": len(runs),
            "statuses": sorted({run.status for run in runs if run.status}),
            "verdicts": verdicts,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _run_dict(self, session: Session, row: TaskRun) -> dict[str, Any]:
        experiment = (
            session.scalar(select(Experiment).where(Experiment.id == row.experiment_id))
            if row.experiment_id
            else None
        )
        evaluation = session.scalar(
            select(EvaluationRecord).where(EvaluationRecord.run_id == row.id)
        )
        observation = session.scalar(
            select(AgentObservation).where(AgentObservation.run_id == row.id)
        )
        artifacts = session.scalars(select(Artifact).where(Artifact.run_id == row.id)).all()
        # The model pair lives in its own table because the two claims differ:
        # what the experiment asked for and what the agent reported serving it.
        model = session.scalar(select(ModelObservation).where(ModelObservation.run_id == row.id))
        plugins = session.scalars(
            select(PluginObservation).where(PluginObservation.run_id == row.id)
        ).all()
        return {
            "uid": row.uid,
            "experiment_uid": experiment.uid if experiment is not None else None,
            "variant_uid": row.variant_uid,
            "task_uid": row.task_uid,
            "agent": f"{row.agent_id}@{row.agent_version}" if row.agent_id else None,
            "session_id": row.session_id,
            "status": row.status,
            "failure_class": row.failure_class,
            "error_message": row.error_message,
            "exit_code": row.exit_code,
            "mode": row.mode,
            "runtime_id": row.runtime_id,
            "requested_model": model.requested_model if model else None,
            "observed_model": model.observed_model if model else None,
            "model_verification": model.verification_status if model else None,
            "repetition": row.repetition,
            "config_hash": row.config_hash,
            "manifest_digest": row.manifest_digest,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "evaluation": (
                {
                    "verdict": evaluation.verdict,
                    "score": evaluation.score,
                    "passed": evaluation.passed,
                    "failed": evaluation.failed,
                    "total": evaluation.total,
                }
                if evaluation
                else None
            ),
            "observations": (
                {
                    "tool_call_count": observation.tool_call_count,
                    # the token split is kept because the three numbers answer
                    # different questions: what was paid for, what the model
                    # generated, and what the two add up to
                    "input_tokens": observation.input_tokens,
                    "cached_input_tokens": observation.cached_input_tokens,
                    "output_tokens": observation.output_tokens,
                    "reasoning_output_tokens": observation.reasoning_output_tokens,
                    "total_tokens": observation.total_tokens,
                }
                if observation
                else None
            ),
            "plugins": [p.plugin_id for p in plugins],
            "artifacts": [
                {
                    "kind": artifact.kind,
                    "path": artifact.path,
                    "filename": Path(artifact.path).name,
                    "checksum": artifact.checksum,
                    "size_bytes": artifact.size_bytes,
                    "content_type": artifact.content_type,
                    "has_data": artifact.data is not None,
                }
                for artifact in artifacts
            ],
        }

    def _metric_dict(self, row: ExperimentMetric) -> dict[str, Any]:
        return {
            "variant_uid": row.variant_uid,
            "metric": row.metric_id,
            "group": row.metric_group,
            "unit": row.unit,
            "runs": row.runs,
            "measured": row.measured,
            "availability": row.availability,
            "mean": row.mean,
            "min": row.minimum,
            "max": row.maximum,
            "deviation": row.deviation,
            "unavailable_reason": row.unavailable_reason,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        }


def _task_texts(loaded: Any) -> tuple[str | None, str | None]:
    """``task.yaml`` and ``description.md`` exactly as written on disk.

    A loaded task that did not come from a directory (a test stub) carries no
    ``path`` and yields ``(None, None)``: the columns stay what was recorded.
    """
    directory = getattr(loaded, "path", None)
    if directory is None:
        return None, None
    directory = Path(directory)
    task_yaml = _read_text(directory / TASK_FILE)
    description_md = _read_text(directory / DESCRIPTION_FILE)
    return task_yaml, description_md


_TASK_FILE_MAX_BYTES = 256 * 1024
_TASK_FILE_SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}
_TASK_FILE_SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".whl",
    ".pyc",
    ".so",
    ".bin",
    ".sqlite",
    ".sqlite3",
}


def _store_task_files(
    session: Session, task_id: int, collected: list[tuple[str, str, str, int, str]]
) -> None:
    """Insert or update one row per collected file, keyed by (task, path).

    Re-recording a task refreshes its files rather than forking them: the code
    of a task is what it was at the digest the task row carries, and a second
    reading of the same directory states the same thing again.
    """
    if not collected:
        return
    existing = {
        row.path: row
        for row in session.scalars(select(TaskFile).where(TaskFile.task_id == task_id)).all()
    }
    now = utc_now()
    for path, kind, content, size_bytes, digest in collected:
        row = existing.get(path)
        if row is None:
            session.add(
                TaskFile(
                    task_id=task_id,
                    path=path,
                    kind=kind,
                    content=content,
                    size_bytes=size_bytes,
                    digest=digest,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.kind = kind
            row.content = content
            row.size_bytes = size_bytes
            row.digest = digest
            row.updated_at = now
    session.flush()


def _repository_root(source: Any, task_dir: Path) -> Path | None:
    """Directory a task's repository source names, or ``None`` when it names none.

    A remote source (a git URL) has no directory to read and is not local code.
    A relative one is resolved against the task directory and its ancestors,
    which finds the project root without importing the dataset that loaded it.
    """
    if not source:
        return None
    text = str(source)
    if "://" in text or text.startswith("git@"):
        return None
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.is_dir() else None
    for base in [task_dir, *task_dir.parents]:
        resolved = base / candidate
        if resolved.is_dir():
            return resolved
    return None


def collect_task_files(loaded: Any) -> list[tuple[str, str, str, int, str]]:
    """The code a task is made of, read from its directory on disk.

    Returns ``(path, kind, content, size_bytes, digest)`` for every file that
    defines the task: the repository it is worked in, the hidden and public
    tests that grade it, and the mutation patch. Paths are relative to where
    the file belongs — the repository root for repository files, the task
    directory for tests and the mutation. Files that cannot be read as text,
    that are binary, or that exceed ``_TASK_FILE_MAX_BYTES`` are skipped:
    a file that cannot be shown is not recorded as an empty file, which
    would be a false statement about the task.
    """
    raw_directory = getattr(loaded, "path", None)
    body = getattr(loaded.task, "task", None)
    if raw_directory is None or body is None:
        return []
    directory = Path(raw_directory)
    collected: list[tuple[str, str, str, int, str]] = []
    seen: set[str] = set()

    def add(kind: str, path: Path, recorded: str) -> None:
        """Record one file under ``recorded``, when it is text worth showing."""
        if recorded in seen or not path.is_file():
            return
        seen.add(recorded)
        try:
            data = path.read_bytes()
        except OSError:
            return
        if len(data) > _TASK_FILE_MAX_BYTES:
            return
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            return
        digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
        collected.append((recorded, kind, content, len(data), digest))

    def walk(kind: str, root: Path, prefix: str = "") -> None:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part in _TASK_FILE_SKIP_DIRS for part in relative.parts):
                continue
            if path.suffix.lower() in _TASK_FILE_SKIP_SUFFIXES:
                continue
            add(kind, path, f"{prefix}{relative.as_posix()}")

    # The repository the task is worked in. A materialized task names it by an
    # absolute path; a bare descriptor names it relative to the project, so the
    # task directory's ancestors are tried until the source resolves.
    repository = getattr(body, "repository", None)
    source = getattr(repository, "source", None)
    repo_root = _repository_root(source, directory)
    if repo_root is not None:
        subdir = getattr(repository, "subdir", None)
        walk("repository", repo_root / subdir if subdir else repo_root)

    # The mutation patch and the tests are named from the task directory, so a
    # path says which part of the task it belongs to as well as where it is.
    mutation = getattr(body, "mutation", None)
    if mutation is not None:
        patch = str(getattr(mutation, "patch", ""))
        if patch:
            add("mutation", directory / patch, patch)

    for kind, configured in (
        ("hidden_tests", getattr(body, "hidden_tests", None)),
        ("public_tests", getattr(body, "public_tests", None)),
    ):
        if not configured:
            continue
        tests = Path(str(configured))
        if (directory / tests).is_dir():
            walk(kind, directory / tests, f"{tests.as_posix()}/")

    return collected


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


_ARTIFACT_KINDS = {
    "run_record.json": "run_record",
    "metadata.json": "metadata",
    "manifest.json": "manifest",
    "events.jsonl": "events",
    "agent_trace.jsonl": "agent_trace",
    "runtime_trace.jsonl": "runtime_trace",
    "tool_calls.jsonl": "tool_calls",
    "evaluation.json": "evaluation",
    "junit.xml": "junit",
    "diff.patch": "diff",
    "solution.patch": "diff",
    "solution_diff.patch": "diff",
    "stdout.log": "stdout",
    "stderr.log": "stderr",
    "pytest-report.xml": "junit",
    "pytest-output.txt": "evaluation_output",
    "solution.zip": "solution_archive",
    "solution_workspace.zip": "solution_archive",
    "agent_traces.zip": "agent_traces_archive",
    "evaluation.zip": "evaluation_archive",
    "evaluation_results.zip": "evaluation_archive",
}


def _artifact_kind(filename: str) -> str:
    if filename in _ARTIFACT_KINDS:
        return _ARTIFACT_KINDS[filename]
    if filename.endswith(".zip"):
        return "archive"
    if filename.endswith(".patch") or filename.endswith(".diff"):
        return "diff"
    if filename.endswith(".jsonl"):
        return "trace"
    if filename.endswith(".json"):
        return "json"
    if filename.endswith(".log") or filename.endswith(".txt"):
        return "log"
    return "file"


def _content_type(filename: str) -> str:
    if filename.endswith(".zip"):
        return "application/zip"
    if filename.endswith(".json"):
        return "application/json"
    if filename.endswith(".jsonl"):
        return "application/x-ndjson"
    if filename.endswith(".xml"):
        return "application/xml"
    if filename.endswith(".patch") or filename.endswith(".diff"):
        return "text/x-diff"
    if filename.endswith(".log") or filename.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"


def _verified_by_log(
    payload: dict[str, Any], requested: Any, evidence: dict[str, Any]
) -> dict[str, Any]:
    """Judge the requested model against the instance's own log.

    An alias is not a lie: the run asked for the alias, the instance received
    it, and the log names what routing made of it. That is recorded as a
    verified alias resolution with the resolved model in ``observed_model``,
    because the claim being verified is "this run went through that alias on
    this instance", not "that name is a real deployment".
    """
    served = [str(name) for name in evidence.get("served_models") or []]
    received = [str(name) for name in evidence.get("received_models") or []]
    decisions = [str(name) for name in evidence.get("routing_decisions") or []]
    log = str(evidence.get("log") or "the instance log")
    result = dict(payload, value_source="log")

    if requested is None:
        # A run that asked for no model cannot mismatch the instance's log; the
        # log still says what was served, and that is worth keeping.
        result.update(
            observed_model=", ".join(served) or None,
            verification_status="unverified",
            note=f"{log} served {', '.join(served) or 'no model'}, but the run requested none",
        )
        return result

    if str(requested) in served:
        result.update(
            observed_model=requested,
            verification_status="verified",
            note=(
                f"verified from {log}: this instance logged forwarding this run's "
                f"requests to {requested}" + _agent_disagreement(payload, served)
            ),
        )
        return result

    if str(requested) in received:
        resolved_names = served or decisions
        result.update(
            observed_model=", ".join(str(name) for name in resolved_names) or None,
            verification_status="verified",
            note=(
                f"verified from {log}: this instance received the alias {requested} and "
                f"routing served {', '.join(str(name) for name in resolved_names) or 'no model'}"
                + _agent_disagreement(payload, received + served)
            ),
        )
        return result

    result.update(
        observed_model=", ".join(served) or result.get("observed_model"),
        verification_status="mismatch",
        note=(
            f"{log} never names {requested}: this instance served "
            f"{', '.join(served) or 'no model'} and received "
            f"{', '.join(received) or 'no model'}"
        ),
    )
    return result


def _agent_disagreement(payload: dict[str, Any], evidence_names: list[str]) -> str:
    """A note when the agent's own report does not match the instance's log."""
    reported = payload.get("observed_model")
    if reported is None or str(reported) in evidence_names:
        return ""
    return f"; the agent reported {reported}, the instance log is the stronger evidence"


def _inventory_note(requested: Any, served_models: Any) -> str:
    """What an inventory alone can honestly say about the requested model."""
    names = [str(name) for name in served_models or []]
    if requested is None:
        return "the instance reported an inventory, but the run requested no model"
    if str(requested) in names:
        return (
            f"the instance lists {requested} among the models it serves; an inventory says "
            "what is available, not which model served this run, so the pairing stays "
            "unverified"
        )
    return (
        f"the instance does not list {requested} among "
        f"{', '.join(names) or 'the models it serves'}; aliases are absent from "
        "GET /v1/models, so its absence is not evidence against the run"
    )

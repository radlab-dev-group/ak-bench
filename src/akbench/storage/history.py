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
from akbench.storage.db import session_scope
from akbench.storage.models import (
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
    Task,
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
        experiment_type: str | None = None,
        descriptor_id: str | None = None,
        descriptor_version: str | None = None,
        config_hash: str | None = None,
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
            experiment.title = title
            experiment.experiment_type = experiment_type
            experiment.descriptor_id = descriptor_id
            experiment.descriptor_version = descriptor_version
            experiment.config_hash = config_hash
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
            if observed_model is not None:
                self._record_model_observation(session, run, observed_model)

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

    def register_artifacts(self, run_uid: str, paths: list[str | Path]) -> list[dict[str, Any]]:
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
                session.add(
                    Artifact(
                        run_id=run.id,
                        kind=info["kind"],
                        path=str(path),
                        checksum=_digest_bytes(data),
                        size_bytes=len(data),
                        content_type=_content_type(path.name),
                        created_at=now,
                        updated_at=now,
                    )
                )
                info["checksum"] = _digest_bytes(data)
                info["size_bytes"] = len(data)
                results.append(info)
            session.flush()
            return results

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
        if task_row is None:
            task_row = Task(
                uid=loaded.uid,
                task_id=str(loaded.task.id),
                version=str(loaded.task.version),
                category=str(loaded.task.category),
                difficulty=str(loaded.task.difficulty),
                evaluator=str(loaded.task.evaluator),
                snapshot_digest=str(loaded.digest),
                created_at=now,
                updated_at=now,
            )
            session.add(task_row)
        task_row.repository_uid = repository_uid
        task_row.base_commit = getattr(loaded.task.task.repository, "ref", None)
        task_row.updated_at = now
        session.flush()

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
        usage = observations.get("token_usage") or {}
        tool_names = observations.get("tool_names") or {}
        tool_call_count = observations.get("tool_call_count")
        if tool_call_count is None and isinstance(tool_names, dict):
            tool_call_count = sum(v for v in tool_names.values() if isinstance(v, int))
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
                input_tokens=usage.get("input_tokens"),
                cached_input_tokens=usage.get("cached_input_tokens"),
                output_tokens=usage.get("output_tokens"),
                reasoning_output_tokens=usage.get("reasoning_output_tokens"),
                total_tokens=usage.get("total_tokens"),
                observations_json=_dump(observations),
                created_at=now,
                updated_at=now,
            )
        )

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
            "type": row.experiment_type,
            "descriptor": f"{row.descriptor_id}@{row.descriptor_version}"
            if row.descriptor_id
            else None,
            "validity": row.validity_status,
            "config_hash": row.config_hash,
            "runs": len(runs),
            "statuses": sorted({run.status for run in runs if run.status}),
            "verdicts": verdicts,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _run_dict(self, session: Session, row: TaskRun) -> dict[str, Any]:
        evaluation = session.scalar(
            select(EvaluationRecord).where(EvaluationRecord.run_id == row.id)
        )
        observation = session.scalar(
            select(AgentObservation).where(AgentObservation.run_id == row.id)
        )
        artifacts = session.scalars(select(Artifact).where(Artifact.run_id == row.id)).all()
        plugins = session.scalars(
            select(PluginObservation).where(PluginObservation.run_id == row.id)
        ).all()
        return {
            "uid": row.uid,
            "experiment_uid": None,
            "variant_uid": row.variant_uid,
            "task_uid": row.task_uid,
            "agent": f"{row.agent_id}@{row.agent_version}" if row.agent_id else None,
            "session_id": row.session_id,
            "status": row.status,
            "failure_class": row.failure_class,
            "exit_code": row.exit_code,
            "mode": row.mode,
            "runtime_id": row.runtime_id,
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
                    "input_tokens": observation.input_tokens,
                    "total_tokens": observation.total_tokens,
                }
                if observation
                else None
            ),
            "plugins": [p.plugin_id for p in plugins],
            "artifacts": [
                {"kind": artifact.kind, "path": artifact.path, "checksum": artifact.checksum}
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
    "stdout.log": "stdout",
    "stderr.log": "stderr",
    "pytest-report.xml": "junit",
    "pytest-output.txt": "evaluation_output",
}


def _artifact_kind(filename: str) -> str:
    if filename in _ARTIFACT_KINDS:
        return _ARTIFACT_KINDS[filename]
    if filename.endswith(".jsonl"):
        return "trace"
    if filename.endswith(".json"):
        return "json"
    if filename.endswith(".log") or filename.endswith(".txt"):
        return "log"
    return "file"


def _content_type(filename: str) -> str:
    if filename.endswith(".json"):
        return "application/json"
    if filename.endswith(".jsonl"):
        return "application/x-ndjson"
    if filename.endswith(".xml"):
        return "application/xml"
    if filename.endswith(".patch"):
        return "text/x-diff"
    if filename.endswith(".log") or filename.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"

"""Persistence model (plan section 19).

The database stores metadata and relations; traces and large artifacts stay on
disk, referenced by path with a checksum. Every row that records what happened
keeps the identity it was observed under — descriptor digests, config hashes,
plugin versions — so a result can still be traced four months later, after the
descriptors have moved on.

Values that were never measured stay ``NULL`` rather than becoming zero: a
missing token count and a token count of zero are different facts, and a
report must be able to tell them apart.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ExperimentValidity(StrEnum):
    """Plan section 23: how much of an experiment result can be trusted."""

    VALID = "valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    INVALID = "invalid"
    INCOMPLETE = "incomplete"


class RunStatus(StrEnum):
    """Run Orchestrator lifecycle (plan section 15)."""

    PENDING = "pending"
    PREPARING = "preparing"
    VALIDATING = "validating"
    CONFIGURING_RUNTIME = "configuring_runtime"
    CREATING_WORKSPACE = "creating_workspace"
    STARTING_AGENT = "starting_agent"
    EXECUTING = "executing"
    COLLECTING = "collecting"
    EVALUATING = "evaluating"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    INVALID_CONFIGURATION = "invalid_configuration"
    EVALUATION_ERROR = "evaluation_error"

    @classmethod
    def terminal(cls) -> frozenset[RunStatus]:
        return frozenset(
            {
                cls.COMPLETED,
                cls.FAILED,
                cls.TIMEOUT,
                cls.CANCELLED,
                cls.INFRASTRUCTURE_ERROR,
                cls.INVALID_CONFIGURATION,
                cls.EVALUATION_ERROR,
            }
        )


class FailureClass(StrEnum):
    """Origin of a run failure; keeps infrastructure errors out of agent scores."""

    AGENT = "agent"
    INFRASTRUCTURE = "infrastructure"
    EVALUATION = "evaluation"
    CANCELLED = "cancelled"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Repository(Base, TimestampMixin):
    """A source repository a task pins its code to (plan section 8.3)."""

    __tablename__ = "repositories"
    __table_args__ = (Index("ix_repositories_source", "source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    default_ref: Mapped[str | None] = mapped_column(String(128))
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="git")
    notes: Mapped[str | None] = mapped_column(Text)


class Task(Base, TimestampMixin):
    """A versioned task as recorded when it was used (plan sections 8.3, 19)."""

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_tasks_task_id_version"),
        Index("ix_tasks_category", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluator: Mapped[str] = mapped_column(String(128), nullable=False)
    repository_uid: Mapped[str | None] = mapped_column(
        ForeignKey("repositories.uid", ondelete="SET NULL")
    )
    base_commit: Mapped[str | None] = mapped_column(String(64))
    mutation_version: Mapped[str | None] = mapped_column(String(64))
    snapshot_digest: Mapped[str] = mapped_column(String(71), nullable=False)


class Experiment(Base, TimestampMixin):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String(255))
    experiment_type: Mapped[str | None] = mapped_column(String(64))
    descriptor_id: Mapped[str | None] = mapped_column(String(128))
    descriptor_version: Mapped[str | None] = mapped_column(String(64))
    validity_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ExperimentValidity.INCOMPLETE
    )
    config_hash: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)


class Benchmark(Base, TimestampMixin):
    """A named grouping of experiments (plan section 19).

    A benchmark is what a set of experiments shares: the same task selection
    and the same questions. It is deliberately thin — the substance lives in
    the experiments — but it gives a report something to aggregate over.
    """

    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)


class DatasetRecord(Base, TimestampMixin):
    """A dataset as recorded when an experiment used it (plan section 19)."""

    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_datasets_dataset_id_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="0.0.0")
    digest: Mapped[str | None] = mapped_column(String(71))
    path: Mapped[str | None] = mapped_column(String(512))
    task_count: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class ExperimentVariant(Base, TimestampMixin):
    """One variant of an experiment matrix (plan 12.3, 19)."""

    __tablename__ = "experiment_variants"
    __table_args__ = (
        UniqueConstraint("experiment_id", "uid", name="uq_experiment_variants_uid"),
        Index("ix_experiment_variants_experiment", "experiment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(64), nullable=False)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    values_json: Mapped[str | None] = mapped_column(Text)
    agent_config_json: Mapped[str | None] = mapped_column(Text)
    environment_requests_json: Mapped[str | None] = mapped_column(Text)
    applies_json: Mapped[str | None] = mapped_column(Text)
    config_hash: Mapped[str | None] = mapped_column(String(64))
    is_baseline: Mapped[bool] = mapped_column(nullable=False, default=False)


class DescriptorSnapshot(Base, TimestampMixin):
    """The exact content of a descriptor a plan depended on (plan section 9).

    Digests alone prove a change happened; keeping the payload makes the
    historical result re-readable, which is what a digest cannot do by itself.
    """

    __tablename__ = "descriptor_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "kind", "descriptor_id", "version",
            name="uq_descriptor_snapshots_identity",
        ),
        Index("ix_descriptor_snapshots_digest", "digest"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    descriptor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    digest: Mapped[str] = mapped_column(String(71), nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(512))


class TaskRun(Base, TimestampMixin):
    __tablename__ = "task_runs"
    __table_args__ = (
        UniqueConstraint("experiment_id", "uid", name="uq_task_runs_experiment_uid"),
        Index("ix_task_runs_status", "status"),
        Index("ix_task_runs_task_uid", "task_uid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(64), nullable=False)
    experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    variant_uid: Mapped[str | None] = mapped_column(String(64))
    task_uid: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("tasks.uid", ondelete="SET NULL")
    )

    agent_id: Mapped[str | None] = mapped_column(String(128))
    agent_version: Mapped[str | None] = mapped_column(String(64))
    adapter_id: Mapped[str | None] = mapped_column(String(128))
    session_id: Mapped[str | None] = mapped_column(String(128))
    workspace_path: Mapped[str | None] = mapped_column(String(512))

    status: Mapped[str] = mapped_column(String(32), nullable=False, default=RunStatus.PENDING)
    failure_class: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    config_hash: Mapped[str | None] = mapped_column(String(64))
    #: Digest of the reproducibility manifest of this run (plan section 14).
    manifest_digest: Mapped[str | None] = mapped_column(String(71))
    mode: Mapped[str | None] = mapped_column(String(32))
    runtime_id: Mapped[str | None] = mapped_column(String(128))
    repetition: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationRecord(Base, TimestampMixin):
    """One evaluator verdict for one run (plan sections 16, 19)."""

    __tablename__ = "evaluations"
    __table_args__ = (Index("ix_evaluations_verdict", "verdict"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"))
    evaluator_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluator_version: Mapped[str | None] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float | None] = mapped_column()
    passed: Mapped[int | None] = mapped_column(Integer)
    failed: Mapped[int | None] = mapped_column(Integer)
    skipped: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column()
    details_json: Mapped[str | None] = mapped_column(Text)
    artifacts_json: Mapped[str | None] = mapped_column(Text)


class MetricRecord(Base, TimestampMixin):
    """The metric catalog, as observed (plan section 18).

    Stored so a historical report can say which metrics were computable at
    the time: a metric that is available today was not necessarily so then.
    """

    __tablename__ = "metrics"
    __table_args__ = (
        UniqueConstraint("metric_id", "version", name="uq_metrics_metric_id_version"),
        Index("ix_metrics_group", "metric_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    title: Mapped[str | None] = mapped_column(String(255))
    metric_group: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[str | None] = mapped_column(String(32))
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    digest: Mapped[str | None] = mapped_column(String(71))


class Artifact(Base, TimestampMixin):
    """One file a run produced, with the checksum that pins its content.

    Traces stay on disk (plan section 19); the row is the pointer plus the
    evidence that the file has not changed since the run wrote it.
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "kind", "path", name="uq_artifacts_run_kind_path"),
        Index("ix_artifacts_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum: Mapped[str] = mapped_column(String(71), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_type: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)


class PluginObservation(Base, TimestampMixin):
    """Plugin state for one run: requested, observed, verified (plan 10.2)."""

    __tablename__ = "plugin_observations"
    __table_args__ = (
        Index("ix_plugin_observations_run", "run_id"),
        Index("ix_plugin_observations_plugin", "plugin_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"))
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plugin_version: Mapped[str | None] = mapped_column(String(64))
    descriptor_digest: Mapped[str | None] = mapped_column(String(71))
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    state_json: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class AgentObservation(Base, TimestampMixin):
    """What the agent itself reported for one run (plan 18.2, 18.3).

    Every numeric field is nullable: an agent that does not report tokens did
    not spend zero of them.
    """

    __tablename__ = "agent_observations"
    __table_args__ = (Index("ix_agent_observations_run", "run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"))
    session_id: Mapped[str | None] = mapped_column(String(128))
    agent_status: Mapped[str | None] = mapped_column(String(32))
    tool_call_count: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    observations_json: Mapped[str | None] = mapped_column(Text)


class ModelObservation(Base, TimestampMixin):
    """Requested versus observed model for one run, with its provenance.

    The agent reports the alias it was asked for; the router reports what
    served the request. They are not the same claim, so they are stored apart
    and the status says how much trust the observed value deserves.
    """

    __tablename__ = "model_observations"
    __table_args__ = (Index("ix_model_observations_run", "run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"))
    requested_model: Mapped[str | None] = mapped_column(String(128))
    observed_model: Mapped[str | None] = mapped_column(String(128))
    value_source: Mapped[str | None] = mapped_column(String(32))
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class ExperimentMetric(Base, TimestampMixin):
    """An aggregate over the runs of one experiment (plan sections 18, 19).

    ``measured`` and ``runs`` are stored next to the mean on purpose: an
    average over two of ten runs is not the same statement as one over ten,
    and a report reader should not have to guess which one this is.
    """

    __tablename__ = "experiment_metrics"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "variant_uid", "metric_id", name="uq_experiment_metrics_identity"
        ),
        Index("ix_experiment_metrics_experiment", "experiment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    variant_uid: Mapped[str | None] = mapped_column(String(64), nullable=False, default="*")
    metric_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_group: Mapped[str | None] = mapped_column(String(32))
    unit: Mapped[str | None] = mapped_column(String(32))
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    measured: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    availability: Mapped[float | None] = mapped_column()
    mean: Mapped[float | None] = mapped_column()
    minimum: Mapped[float | None] = mapped_column()
    maximum: Mapped[float | None] = mapped_column()
    deviation: Mapped[float | None] = mapped_column()
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventLog(Base, TimestampMixin):
    """Append-only events: lifecycle transitions and notable findings (plan 19)."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_run", "run_id"),
        Index("ix_events_experiment", "experiment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_runs.id", ondelete="CASCADE")
    )
    experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str | None] = mapped_column(Text)

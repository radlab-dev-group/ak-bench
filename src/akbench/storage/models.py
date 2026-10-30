"""Core persistence model for Faza 1.

Deliberately small: the complete data model (metrics, observations, descriptor
snapshots, events) lands in Faza 11. ``task_uid`` is a plain identifier here
and becomes a real foreign key when the dataset layer exists in Faza 3.
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
    task_uid: Mapped[str | None] = mapped_column(String(128))

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
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""core tables: experiments and task_runs

Revision ID: 0001
Revises:
Create Date: 2026-10-30

Faza 1 scope. Metrics, observations, descriptor snapshots and events arrive in
Faza 11; ``task_uid`` becomes a foreign key when the dataset layer exists.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("experiment_type", sa.String(length=64), nullable=True),
        sa.Column("descriptor_id", sa.String(length=128), nullable=True),
        sa.Column("descriptor_version", sa.String(length=64), nullable=True),
        sa.Column("validity_status", sa.String(length=32), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid", name="uq_experiments_uid"),
    )

    op.create_table(
        "task_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("variant_uid", sa.String(length=64), nullable=True),
        sa.Column("task_uid", sa.String(length=128), nullable=True),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("agent_version", sa.String(length=64), nullable=True),
        sa.Column("adapter_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("workspace_path", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_class", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("config_hash", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["experiments.id"], name="fk_task_runs_experiment_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "uid", name="uq_task_runs_experiment_uid"),
    )
    op.create_index("ix_task_runs_status", "task_runs", ["status"])
    op.create_index("ix_task_runs_task_uid", "task_runs", ["task_uid"])


def downgrade() -> None:
    op.drop_index("ix_task_runs_task_uid", table_name="task_runs")
    op.drop_index("ix_task_runs_status", "task_runs")
    op.drop_table("task_runs")
    op.drop_table("experiments")

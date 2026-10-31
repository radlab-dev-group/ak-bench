"""dataset layer: repositories and tasks

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30

Phase 3. Records the source repositories a task pins its code to and the
versioned tasks themselves, and turns ``task_runs.task_uid`` into a reference
to a real task row (the dataset layer exists from here on).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("default_ref", sa.String(length=128), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid", name="uq_repositories_uid"),
    )
    op.create_index("ix_repositories_source", "repositories", ["source"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("difficulty", sa.String(length=32), nullable=False),
        sa.Column("evaluator", sa.String(length=128), nullable=False),
        sa.Column("repository_uid", sa.String(length=128), nullable=True),
        sa.Column("base_commit", sa.String(length=64), nullable=True),
        sa.Column("mutation_version", sa.String(length=64), nullable=True),
        sa.Column("snapshot_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_uid"],
            ["repositories.uid"],
            name="fk_tasks_repository_uid",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid", name="uq_tasks_uid"),
        sa.UniqueConstraint("task_id", "version", name="uq_tasks_task_id_version"),
    )
    op.create_index("ix_tasks_category", "tasks", ["category"])

    # SQLite cannot add a foreign key in place, hence batch mode.
    with op.batch_alter_table("task_runs") as batch_op:
        batch_op.create_foreign_key(
            "fk_task_runs_task_uid", "tasks", ["task_uid"], ["uid"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("task_runs") as batch_op:
        batch_op.drop_constraint("fk_task_runs_task_uid", type_="foreignkey")
    op.drop_index("ix_tasks_category", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_repositories_source", table_name="repositories")
    op.drop_table("repositories")

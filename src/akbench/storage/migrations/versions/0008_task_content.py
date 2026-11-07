"""task content: the prose that belongs to the task itself

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-06

The database kept a task's identity and its digest, but not what the task
actually asks: the title and description the YAML declares, the full
descriptor, and the ``description.md`` that states the complete scope of the
work. Every one of them travels with the task row now, so the history stands
alone: a reader of the UI does not need the dataset checkout to see what a
recorded run was about, and a dataset edited after a run cannot rewrite what
was recorded.

``task_yaml`` stores the descriptor exactly as loaded, and
``description_md`` the markdown file verbatim; both stay ``NULL`` for tasks
recorded before this revision until ``scripts/update_task_info.py`` backfills
them from the dataset on disk.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("task_yaml", sa.Text(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("description_md", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "description_md")
    op.drop_column("tasks", "task_yaml")
    op.drop_column("tasks", "description")

"""task created_at and authors

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-02

Tasks can define their original creation timestamp (`created_at`) and their
`authors` list. Recording them ensures task authorship and original timeline
are tracked in database history and reports.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("task_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("authors_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "authors_json")
    op.drop_column("tasks", "task_created_at")

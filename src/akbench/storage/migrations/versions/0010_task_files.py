"""task files: the code a task is made of

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-06

The prose of a task — its title, its description, its descriptor — now
travels with its row, but the *code* does not: the repository a task is
worked in, the hidden and public tests that grade it, and the mutation that
planted the defect all stayed on the dataset disk. A history read without
that checkout can name a task and quote what it asks, yet cannot show the
code the agent was actually handed or the tests it was graded by.

``task_files`` is a child table of ``tasks``: one row per file, the path
relative to where the file belongs (the repository root, or the task
directory for tests and the mutation patch) and the kind that says which
part of the task it is. Content is stored verbatim, with a size and a
sha256 digest, so a file can be shown, and later proven unchanged, from the
history alone. Rows stay empty for tasks recorded before this revision
until ``scripts/update_task_info.py`` backfills them from the dataset.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "path", name="uq_task_files_task_id_path"),
    )
    op.create_index("ix_task_files_task_id", "task_files", ["task_id"])
    op.create_index("ix_task_files_kind", "task_files", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_task_files_kind", table_name="task_files")
    op.drop_index("ix_task_files_task_id", table_name="task_files")
    op.drop_table("task_files")

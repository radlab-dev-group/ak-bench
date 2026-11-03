"""artifact data column

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-03

Add binary data column to artifacts table to persist archive payloads and diffs directly in the database.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column("data", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.drop_column("data")

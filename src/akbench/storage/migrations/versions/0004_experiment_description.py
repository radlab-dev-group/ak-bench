"""the description an experiment states about itself

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02

An experiment file has always been able to carry a ``description``, but the
history kept only the title, so the sentence saying what an experiment asks —
and on what it refuses to be compared — was lost the moment the plan was
recorded. A report read a week later showed a title and a matrix with no way
to recover the intent behind them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("experiments", "description")

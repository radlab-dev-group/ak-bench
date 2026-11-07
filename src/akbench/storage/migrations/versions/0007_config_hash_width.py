"""config_hash width

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06

``config_hash`` carried 64 characters, but every hash AK-Bench writes is
``sha256:<64 hex>`` — 71 characters, which is what the digest columns already
declare. SQLite never enforced the length, so the recorded history outgrew its
own schema unnoticed; PostgreSQL does enforce it, and importing that history
fails on the first row. The column becomes what the code has always written.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, column) of every hash that carries the ``sha256:`` prefix.
HASH_COLUMNS: tuple[tuple[str, str], ...] = (
    ("experiments", "config_hash"),
    ("experiment_variants", "config_hash"),
    ("task_runs", "config_hash"),
)


def upgrade() -> None:
    for table, column in HASH_COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                column,
                existing_type=sa.String(length=64),
                type_=sa.String(length=71),
                existing_nullable=True,
            )


def downgrade() -> None:
    for table, column in HASH_COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                column,
                existing_type=sa.String(length=71),
                type_=sa.String(length=64),
                existing_nullable=True,
            )

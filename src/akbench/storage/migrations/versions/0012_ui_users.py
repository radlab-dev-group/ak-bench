"""ui users: who may sign in to the dashboard, kept as hashes

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-14

The dashboard read its users from the environment or a text file, and the
secrets sat there in plain text next to the process that served them. They
now live in this database: one row per person, carrying a salted iterated
digest of their secret and the role the navigation and the admin gate read.

A password is stored as ``pbkdf2_sha256$<iterations>$<salt>$<hash>`` — never
in its own letters. The role is one of ``viewer``, ``judge``, ``admin``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ui_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="viewer"),
        sa.Column("session_cutoff", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ui_users_name", "ui_users", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ui_users_name", table_name="ui_users")
    op.drop_table("ui_users")

"""experiment content, agents and runtimes

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-06

The same rule that moved a task's prose into its row now covers the other
components a run was made of: the experiment's own descriptor, and the
agent and the runtime it ran under.

``experiments`` gains the descriptor file it was planned from, so an
experiment page can be read from history alone. ``agents`` and ``runtimes``
are new tables keyed by the plain id a run already carries in
``task_runs.agent_id`` / ``task_runs.runtime_id``: a run that names an agent
names a row, and the row carries the descriptor the component declared at
that version. A versioned descriptor is stored per (id, version); the run
links by id alone because that is what it recorded.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column("experiment_yaml", sa.Text(), nullable=True),
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agent_yaml", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agents_agent_id_version"),
    )
    op.create_index("ix_agents_agent_id", "agents", ["agent_id"])

    op.create_table(
        "runtimes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("runtime_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("runtime_yaml", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("runtime_id", "version", name="uq_runtimes_runtime_id_version"),
    )
    op.create_index("ix_runtimes_runtime_id", "runtimes", ["runtime_id"])


def downgrade() -> None:
    op.drop_index("ix_runtimes_runtime_id", table_name="runtimes")
    op.drop_table("runtimes")
    op.drop_index("ix_agents_agent_id", table_name="agents")
    op.drop_table("agents")
    op.drop_column("experiments", "experiment_yaml")

"""evaluator lists: a task may be judged by more than one evaluator

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-12

``tasks.evaluator`` said a task had exactly one judge. A task can now declare a
list, and the verdict is composed from all of them (see
``akbench.evaluators.task_evaluation``). Two things follow for the history.

``tasks.evaluators`` records the whole declared set. ``tasks.evaluator`` stays
exactly as it was — the primary, the first declared — because every existing
reader quotes one evaluator, and a historical row must keep meaning what it
meant when it was written.

The composed verdict arrives with one entry per evaluator that ran, and those
are now kept as one ``evaluations`` row each, which is what that table has
always been for ("one evaluator verdict for one run").

Two readers take *the* verdict of a run, and neither ordered its rows, so adding
rows would have made "the" verdict an accident of storage order.
``evaluations.evaluator_rank`` is what removes the accident: rank 0 is the row a
reader quotes — the composed verdict for a run judged several ways, the single
verdict otherwise — and the per-evaluator rows follow it. Existing rows get rank
0, which is exactly what they always were.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("evaluators", sa.Text(), nullable=True))
    op.add_column(
        "evaluations",
        sa.Column("evaluator_rank", sa.Integer(), nullable=False, server_default="0"),
    )
    # A row written before this revision declared one evaluator; that evaluator
    # *was* the whole set, so the new column is filled from the old one rather
    # than left empty and re-derived at read time.
    tasks = sa.table("tasks", sa.column("evaluator", sa.String), sa.column("evaluators", sa.Text))
    op.execute(tasks.update().where(tasks.c.evaluators.is_(None)).values(evaluators=tasks.c.evaluator))


def downgrade() -> None:
    # The extra per-evaluator rows a multi-evaluator run wrote have no home in
    # a schema that quotes one verdict per run; the rank-0 row is the one that
    # survives, because it is the one every reader was already quoting.
    evaluations = sa.table(
        "evaluations",
        sa.column("evaluator_rank", sa.Integer),
    )
    op.execute(evaluations.delete().where(evaluations.c.evaluator_rank > 0))
    op.drop_column("evaluations", "evaluator_rank")
    op.drop_column("tasks", "evaluators")

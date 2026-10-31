"""experiment history: variants, evaluations, metrics, observations, artifacts

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31

Phase 11. The history of an experiment is the thing a benchmark report is
built from, so it gets a row of its own: the plan's variants, the verdict of
each evaluation, what the agent, the plugins and the router reported, the
artifacts a run left behind (with a checksum, because a pointer to a file that
has since changed proves nothing), the descriptor content a plan depended on,
and the events a run produced.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmarks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid", name="uq_benchmarks_uid"),
    )

    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=128), nullable=False),
        sa.Column("dataset_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=True),
        sa.Column("path", sa.String(length=512), nullable=True),
        sa.Column("task_count", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid", name="uq_datasets_uid"),
        sa.UniqueConstraint("dataset_id", "version", name="uq_datasets_dataset_id_version"),
    )

    op.create_table(
        "experiment_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("values_json", sa.Text(), nullable=True),
        sa.Column("agent_config_json", sa.Text(), nullable=True),
        sa.Column("environment_requests_json", sa.Text(), nullable=True),
        sa.Column("applies_json", sa.Text(), nullable=True),
        sa.Column("config_hash", sa.String(length=64), nullable=True),
        sa.Column("is_baseline", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name="fk_experiment_variants_experiment_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "uid", name="uq_experiment_variants_uid"),
    )
    op.create_index(
        "ix_experiment_variants_experiment", "experiment_variants", ["experiment_id"]
    )

    op.create_table(
        "descriptor_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("descriptor_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name="fk_descriptor_snapshots_experiment_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id",
            "kind",
            "descriptor_id",
            "version",
            name="uq_descriptor_snapshots_identity",
        ),
    )
    op.create_index("ix_descriptor_snapshots_digest", "descriptor_snapshots", ["digest"])

    # Phase 11 columns on the run record. SQLite needs batch mode for this.
    with op.batch_alter_table("task_runs") as batch_op:
        batch_op.add_column(sa.Column("manifest_digest", sa.String(length=71), nullable=True))
        batch_op.add_column(sa.Column("mode", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("runtime_id", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("repetition", sa.Integer(), nullable=False, server_default="1")
        )

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("evaluator_id", sa.String(length=128), nullable=False),
        sa.Column("evaluator_version", sa.String(length=64), nullable=True),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Double(), nullable=True),
        sa.Column("passed", sa.Integer(), nullable=True),
        sa.Column("failed", sa.Integer(), nullable=True),
        sa.Column("skipped", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Double(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("artifacts_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_runs.id"],
            name="fk_evaluations_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluations_verdict", "evaluations", ["verdict"])

    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("metric_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("metric_group", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("direction", sa.String(length=32), nullable=True),
        sa.Column("availability", sa.String(length=32), nullable=False),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("digest", sa.String(length=71), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("metric_id", "version", name="uq_metrics_metric_id_version"),
    )
    op.create_index("ix_metrics_group", "metrics", ["metric_group"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=71), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_runs.id"],
            name="fk_artifacts_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "kind", "path", name="uq_artifacts_run_kind_path"),
    )
    op.create_index("ix_artifacts_run", "artifacts", ["run_id"])

    op.create_table(
        "plugin_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("plugin_id", sa.String(length=128), nullable=False),
        sa.Column("plugin_version", sa.String(length=64), nullable=True),
        sa.Column("descriptor_digest", sa.String(length=71), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_runs.id"],
            name="fk_plugin_observations_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plugin_observations_run", "plugin_observations", ["run_id"])
    op.create_index("ix_plugin_observations_plugin", "plugin_observations", ["plugin_id"])

    op.create_table(
        "agent_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("agent_status", sa.String(length=32), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("observations_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_runs.id"],
            name="fk_agent_observations_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_observations_run", "agent_observations", ["run_id"])

    op.create_table(
        "model_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("requested_model", sa.String(length=128), nullable=True),
        sa.Column("observed_model", sa.String(length=128), nullable=True),
        sa.Column("value_source", sa.String(length=32), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_runs.id"],
            name="fk_model_observations_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_observations_run", "model_observations", ["run_id"])

    op.create_table(
        "experiment_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("variant_uid", sa.String(length=64), nullable=False),
        sa.Column("metric_id", sa.String(length=128), nullable=False),
        sa.Column("metric_group", sa.String(length=32), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("runs", sa.Integer(), nullable=False),
        sa.Column("measured", sa.Integer(), nullable=False),
        sa.Column("availability", sa.Double(), nullable=True),
        sa.Column("mean", sa.Double(), nullable=True),
        sa.Column("minimum", sa.Double(), nullable=True),
        sa.Column("maximum", sa.Double(), nullable=True),
        sa.Column("deviation", sa.Double(), nullable=True),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name="fk_experiment_metrics_experiment_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id", "variant_uid", "metric_id", name="uq_experiment_metrics_identity"
        ),
    )
    op.create_index("ix_experiment_metrics_experiment", "experiment_metrics", ["experiment_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_runs.id"],
            name="fk_events_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name="fk_events_experiment_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_run", "events", ["run_id"])
    op.create_index("ix_events_experiment", "events", ["experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_events_experiment", table_name="events")
    op.drop_index("ix_events_run", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_experiment_metrics_experiment", table_name="experiment_metrics")
    op.drop_table("experiment_metrics")
    op.drop_index("ix_model_observations_run", table_name="model_observations")
    op.drop_table("model_observations")
    op.drop_index("ix_agent_observations_run", table_name="agent_observations")
    op.drop_table("agent_observations")
    op.drop_index("ix_plugin_observations_plugin", table_name="plugin_observations")
    op.drop_index("ix_plugin_observations_run", table_name="plugin_observations")
    op.drop_table("plugin_observations")
    op.drop_index("ix_artifacts_run", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_metrics_group", table_name="metrics")
    op.drop_table("metrics")
    op.drop_index("ix_evaluations_verdict", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index("ix_descriptor_snapshots_digest", table_name="descriptor_snapshots")
    op.drop_table("descriptor_snapshots")
    op.drop_index("ix_experiment_variants_experiment", table_name="experiment_variants")
    op.drop_table("experiment_variants")
    op.drop_table("datasets")
    op.drop_table("benchmarks")

    with op.batch_alter_table("task_runs") as batch_op:
        batch_op.drop_column("repetition")
        batch_op.drop_column("runtime_id")
        batch_op.drop_column("mode")
        batch_op.drop_column("manifest_digest")

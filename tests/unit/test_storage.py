from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from akbench.core.errors import DatabaseError
from akbench.core.time import utc_now
from akbench.storage.db import (
    create_db_engine,
    database_path_from_url,
    engine_is_reachable,
    session_scope,
)
from akbench.storage.migrator import head_revision, schema_status, upgrade
from akbench.storage.models import Experiment, ExperimentValidity, RunStatus, TaskRun


def test_database_path_from_url() -> None:
    assert database_path_from_url("sqlite:////tmp/a.sqlite") == Path("/tmp/a.sqlite")
    assert database_path_from_url("sqlite:///:memory:") is None
    assert database_path_from_url("postgresql://host/db") is None


def test_relative_sqlite_url_is_rejected() -> None:
    with pytest.raises(DatabaseError, match="absolute"):
        create_db_engine("sqlite:///data/relative.sqlite")


def test_upgrade_creates_tables_and_foreign_keys(database_url: str) -> None:
    _, after = upgrade(database_url)
    assert after == head_revision()

    engine = create_db_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert {"experiments", "task_runs", "alembic_version"} <= tables
        fks = inspect(engine).get_foreign_keys("task_runs")
        assert any(fk["referred_table"] == "experiments" for fk in fks)
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(database_url: str) -> None:
    upgrade(database_url)
    _, after = upgrade(database_url)
    status = schema_status(database_url)
    assert after == status.current == status.head
    assert status.at_head


def test_schema_status_before_init(database_url: str) -> None:
    status = schema_status(database_url)
    assert not status.initialized
    assert status.current is None
    assert "not initialized" in status.describe()


def test_sqlite_pragmas_enabled(database_url: str) -> None:
    from sqlalchemy import text

    upgrade(database_url)
    engine = create_db_engine(database_url)
    try:
        with engine.connect() as connection:
            mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
    finally:
        engine.dispose()
    assert str(mode).lower() == "wal"
    assert int(foreign_keys) == 1


def test_engine_is_reachable_reports_failure(tmp_path: Path) -> None:
    missing_parent = tmp_path / "nope" / "nested"
    engine = create_db_engine(f"sqlite:///{missing_parent / 'db.sqlite'}")
    try:
        with pytest.raises(DatabaseError, match="not reachable"):
            engine_is_reachable(engine)
    finally:
        engine.dispose()


def test_experiment_and_run_roundtrip(database_url: str) -> None:
    upgrade(database_url)
    engine = create_db_engine(database_url)
    try:
        with session_scope(engine) as session:
            experiment = Experiment(
                uid="exp-0001",
                title="Knowledge x model",
                experiment_type="configuration",
                validity_status=ExperimentValidity.INCOMPLETE,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(experiment)
            session.flush()
            session.add(
                TaskRun(
                    uid="run-0001",
                    experiment_id=experiment.id,
                    task_uid="bugfix-001",
                    agent_id="codex",
                    adapter_id="codex_cli",
                    status=RunStatus.PENDING,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )

        with session_scope(engine) as session:
            stored = session.scalar(select(Experiment).where(Experiment.uid == "exp-0001"))
            runs = list(session.scalars(select(TaskRun)))
            assert stored is not None
            assert stored.validity_status == "incomplete"
            assert len(runs) == 1
            assert runs[0].status == "pending"
            assert runs[0].uid == "run-0001"
    finally:
        engine.dispose()


def test_run_uid_unique_per_experiment(database_url: str) -> None:
    upgrade(database_url)
    engine = create_db_engine(database_url)
    try:
        with session_scope(engine) as session:
            experiment = Experiment(uid="exp-0002", created_at=utc_now(), updated_at=utc_now())
            session.add(experiment)
            session.flush()
            experiment_id = experiment.id
            session.add(
                TaskRun(
                    uid="run-dup",
                    experiment_id=experiment_id,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
        with pytest.raises(IntegrityError), session_scope(engine) as session:
            session.add(
                TaskRun(
                    uid="run-dup",
                    experiment_id=experiment_id,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
    finally:
        engine.dispose()


def test_session_scope_rolls_back_on_error(database_url: str) -> None:
    upgrade(database_url)
    engine = create_db_engine(database_url)
    try:
        with pytest.raises(RuntimeError), session_scope(engine) as session:
            session.add(
                Experiment(uid="exp-rollback", created_at=utc_now(), updated_at=utc_now())
            )
            raise RuntimeError("boom")

        with session_scope(engine) as session:
            assert session.scalar(select(Experiment)) is None
    finally:
        engine.dispose()


def test_run_status_terminal_set() -> None:
    terminal = RunStatus.terminal()
    assert RunStatus.COMPLETED in terminal
    assert RunStatus.INFRASTRUCTURE_ERROR in terminal
    assert RunStatus.EXECUTING not in terminal

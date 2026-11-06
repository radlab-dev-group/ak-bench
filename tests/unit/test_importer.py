"""Namespace naming and the guards of a SQLite import."""

from __future__ import annotations

import pytest

from akbench.core.errors import DatabaseError
from akbench.storage.db import namespace_of_url, search_path_url
from akbench.storage.importer import (
    import_sqlite,
    normalize_namespace,
    validate_namespace,
)

POSTGRES = "postgresql+psycopg://akbench:local@127.0.0.1:5959/akbench"


def test_namespace_is_derived_from_the_file_name() -> None:
    assert normalize_namespace("data/akbench.sqlite") == "akbench"
    assert normalize_namespace("/tmp/Knowledge-Replay.db") == "knowledge_replay"
    assert normalize_namespace("runs/2026-11-06.sqlite3") == "2026_11_06"


def test_an_unusable_file_name_is_refused_rather_than_guessed() -> None:
    with pytest.raises(DatabaseError, match="cannot derive a namespace"):
        normalize_namespace("data/.sqlite")


@pytest.mark.parametrize("value", ["Knowledge_Replay", "run-2", "  spaced  "])
def test_a_supplied_namespace_is_normalized_before_it_is_validated(value: str) -> None:
    assert validate_namespace(normalize_namespace(value)).isidentifier()


@pytest.mark.parametrize("value", ["public", "PUBLIC", "information_schema", "alembic"])
def test_a_reserved_schema_name_is_not_a_namespace(value: str) -> None:
    with pytest.raises(DatabaseError, match="reserved"):
        validate_namespace(value)


@pytest.mark.parametrize("value", ["2runs", "with space", "with-dash", "x" * 49, ""])
def test_a_name_postgres_would_reject_is_not_a_namespace(value: str) -> None:
    with pytest.raises(DatabaseError, match="invalid namespace"):
        validate_namespace(value)


def test_a_namespace_travels_in_the_connection() -> None:
    url = search_path_url(POSTGRES, "knowledge_replay")
    assert namespace_of_url(url) == "knowledge_replay"
    assert search_path_url(POSTGRES, None) == POSTGRES
    assert namespace_of_url(POSTGRES) is None


def test_a_namespace_replaces_the_search_path_it_already_carried() -> None:
    url = search_path_url(search_path_url(POSTGRES, "first"), "second")
    assert namespace_of_url(url) == "second"
    assert url.count("search_path") == 1


def test_an_import_from_a_postgres_source_is_refused() -> None:
    with pytest.raises(DatabaseError, match="must be a SQLite"):
        import_sqlite(POSTGRES, POSTGRES, namespace="x")


def test_an_import_into_a_sqlite_target_is_refused() -> None:
    with pytest.raises(DatabaseError, match="must be PostgreSQL"):
        import_sqlite("sqlite:////tmp/a.sqlite", "sqlite:////tmp/b.sqlite")


def test_the_postgres_import_needs_no_server_until_it_runs() -> None:
    """The guards fire before any connection, so a typo costs nothing."""
    with pytest.raises(DatabaseError, match="must be a SQLite"):
        import_sqlite("postgresql+psycopg://nowhere/db", POSTGRES)


@pytest.mark.postgres
def test_two_histories_with_the_same_keys_coexist() -> None:
    """The point of a namespace: two files, one server, no collision."""
    import os

    import sqlalchemy as sa
    from sqlalchemy import text

    from akbench.storage.db import create_db_engine
    from akbench.storage.migrator import upgrade

    target = os.environ.get("AKBENCH_TEST_POSTGRES_URL")
    if not target:
        pytest.skip("set AKBENCH_TEST_POSTGRES_URL to run the PostgreSQL import test")

    sources = []
    for index in (1, 2):
        path = f"/tmp/akbench_collision_{index}.sqlite"
        sources.append((path, f"sqlite:///{path}"))
        upgrade(sources[-1][1])
        engine = create_db_engine(sources[-1][1])
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO experiments (id, uid, title, validity_status, created_at,"
                    " updated_at) VALUES (1, :uid, :title, 'valid',"
                    " '2026-11-06 09:00:00', '2026-11-06 09:00:00')"
                ),
                {"uid": f"same-uid-{index}", "title": f"history {index}"},
            )
        engine.dispose()

    try:
        for index, (_, url) in enumerate(sources, start=1):
            report = import_sqlite(url, target, namespace=f"akbench_test_{index}", replace=True)
            assert report.rows >= 1

        engine = create_db_engine(target)
        for index in (1, 2):
            with engine.connect() as conn:
                row = conn.execute(
                    text(f'SELECT uid, title FROM "akbench_test_{index}".experiments WHERE id=1')
                ).one()
            assert row[0] == f"same-uid-{index}"
        engine.dispose()
        # and the sequences are ahead of the copied rows in every namespace
        engine = create_db_engine(search_path_url(target, "akbench_test_1"))
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO experiments (uid, title, validity_status, created_at,"
                    " updated_at) VALUES ('after-the-copy', 'x', 'valid',"
                    " '2026-11-06 09:00:00', '2026-11-06 09:00:00')"
                )
            )
        engine.dispose()
    finally:
        engine = create_db_engine(target)
        with engine.begin() as conn:
            for index in (1, 2):
                conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "akbench_test_{index}" CASCADE'))
        engine.dispose()
        for path, _ in sources:
            os.unlink(path)

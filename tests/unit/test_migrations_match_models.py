"""The 0001 migration must produce exactly what the ORM declares."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from akbench.storage.db import create_db_engine
from akbench.storage.migrator import upgrade
from akbench.storage.models import Base


def test_migration_matches_models(database_url: str) -> None:
    upgrade(database_url)
    engine = create_db_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert diff == [], f"migration and models diverge: {diff}"

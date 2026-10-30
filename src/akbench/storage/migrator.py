"""Programmatic Alembic access.

The migration scripts live inside the package, so ``akbench`` works after a
plain ``pip install`` without an ``alembic.ini`` in the working directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from akbench.core.errors import DatabaseError
from akbench.storage.db import create_db_engine, database_path_from_url

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _escape(value: str) -> str:
    """Alembic reads options through configparser, so ``%`` must be doubled."""
    return value.replace("%", "%%")


def build_config(database_url: str) -> AlembicConfig:
    config = AlembicConfig()
    config.set_main_option("script_location", _escape(str(MIGRATIONS_DIR)))
    config.set_main_option("version_locations", _escape(str(MIGRATIONS_DIR / "versions")))
    config.set_main_option("sqlalchemy.url", _escape(database_url))
    config.set_main_option("path_separator", _escape(os.pathsep))
    return config


def head_revision() -> str:
    """Highest revision available in the package."""
    script = ScriptDirectory.from_config(build_config("sqlite:///"))
    head = script.get_current_head()
    if head is None:
        raise DatabaseError(f"no migrations found in {MIGRATIONS_DIR / 'versions'}")
    return head


def current_revision(engine: Engine) -> str | None:
    """Revision the database is currently stamped with, or ``None``."""
    try:
        return MigrationContext.configure(engine.connect()).get_current_revision()
    except Exception as exc:
        raise DatabaseError(f"cannot read migration revision: {exc}") from exc


def upgrade(database_url: str, revision: str = "head") -> tuple[str | None, str]:
    """Apply migrations. Returns ``(revision_before, revision_after)``."""
    path = database_path_from_url(database_url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)

    before = current_revision(create_db_engine(database_url))
    try:
        command.upgrade(build_config(database_url), revision)
    except Exception as exc:
        raise DatabaseError(f"migration to {revision!r} failed: {exc}") from exc
    after = current_revision(create_db_engine(database_url))
    return before, after


def downgrade(database_url: str, revision: str = "base") -> tuple[str | None, str | None]:
    before = current_revision(create_db_engine(database_url))
    try:
        command.downgrade(build_config(database_url), revision)
    except Exception as exc:
        raise DatabaseError(f"migration to {revision!r} failed: {exc}") from exc
    return before, current_revision(create_db_engine(database_url))


def is_initialized(database_url: str) -> bool:
    """True when the AK-Bench tables exist (migrations may not be at head)."""
    engine = create_db_engine(database_url)
    try:
        existing = set(inspect(engine).get_table_names())
    except Exception:
        return False
    finally:
        engine.dispose()
    return {"experiments", "task_runs"}.issubset(existing)


def schema_status(database_url: str) -> SchemaStatus:
    """Summarise migration state for ``akbench doctor`` and ``akbench init``."""
    engine = create_db_engine(database_url)
    try:
        existing = set(inspect(engine).get_table_names())
        stamped = current_revision(engine)
    except DatabaseError:
        existing, stamped = set(), None
    finally:
        engine.dispose()

    available = head_revision()
    return SchemaStatus(
        current=stamped,
        head=available,
        tables=sorted(existing),
        initialized=bool({"experiments", "task_runs"} <= existing),
    )


@dataclass(frozen=True)
class SchemaStatus:
    current: str | None
    head: str
    tables: list[str]
    initialized: bool

    @property
    def at_head(self) -> bool:
        return self.current == self.head

    def describe(self) -> str:
        if not self.initialized and self.current is None:
            return "not initialized"
        state = "head" if self.at_head else f"behind head ({self.head})"
        return f"revision {self.current} · {state} · {len(self.tables)} tables"

"""Alembic environment for AK-Bench.

The URL comes from the parent ``AlembicConfig`` (see ``akbench.storage.migrator``)
or from ``AKBENCH_MIGRATION_DATABASE_URL`` when Alembic is invoked directly.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT.parent))

from akbench.storage.models import Base  # noqa: E402

ENV_DATABASE_URL = "AKBENCH_MIGRATION_DATABASE_URL"

config = context.config
if config.config_file_name is not None and os.path.isfile(config.config_file_name):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get(ENV_DATABASE_URL) or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "no database URL for migrations; set sqlalchemy.url or " + ENV_DATABASE_URL
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

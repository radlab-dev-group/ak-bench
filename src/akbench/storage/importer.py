"""Import a SQLite history into one PostgreSQL database, namespace by namespace.

The SQLite file was always the single history of one working directory, so two
of them collide on the first primary key. PostgreSQL keeps them apart with
schemas: one namespace per imported file, each migrated by the Alembic
revisions and each readable by pointing AK-Bench at it
(``database.postgres.schema``).

Three rules make the result trustworthy:

- **Schema first, by migration.** The tables come from the Alembic revisions,
  never from the copy, so the namespace is stamped at the revision the code
  expects. ``alembic_version`` itself is never copied: a stamped but empty
  namespace would claim a schema it does not have.
- **Children after parents.** The order comes from the model metadata, so it
  follows the foreign keys instead of a hand-written list that rots the first
  time a table is added.
- **Counts, or nothing.** Every table is counted on both sides and a difference
  is an error, not a warning: a silently partial history still answers
  questions, wrongly.

SQLite stores the UTC instants without an offset, so a naive datetime is
re-anchored to UTC on the way in; letting PostgreSQL read it as local time
would move every recorded run in time.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, Integer, Table, inspect, make_url, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from akbench.core.errors import DatabaseError
from akbench.storage.db import (
    create_db_engine,
    database_path_from_url,
    search_path_url,
)
from akbench.storage.migrator import head_revision, upgrade

#: Never copied: Alembic's own bookkeeping belongs to the target's migrations.
EXCLUDED_TABLES = frozenset({"alembic_version"})

#: Rows per INSERT. Keeps the 180 MB artifact table out of one statement
#: without turning the copy into one round trip per row.
BATCH_ROWS = 500

#: A namespace becomes a PostgreSQL schema, so it must be a bare identifier:
#: lower case, no quotes needed, short enough for PostgreSQL to accept.
NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

#: Names a namespace may not take: the schema AK-Bench itself uses, and the
#: names PostgreSQL already means something by.
RESERVED_NAMESPACES = frozenset({"public", "information_schema", "alembic", "pg_catalog"})


@dataclass(frozen=True)
class ImportReport:
    """What one import moved, table by table."""

    source: str
    target: str
    namespace: str | None
    revision: str
    created: bool
    tables: tuple[tuple[str, int], ...] = ()

    @property
    def rows(self) -> int:
        return sum(count for _, count in self.tables)

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "namespace": self.namespace,
            "revision": self.revision,
            "created": self.created,
            "rows": self.rows,
            "tables": [{"table": name, "rows": count} for name, count in self.tables],
        }

    def describe(self) -> str:
        where = f"namespace {self.namespace}" if self.namespace else "the default schema"
        return (
            f"imported {self.rows} rows over {len(self.tables)} tables into {where} "
            f"at revision {self.revision}"
        )


@dataclass(frozen=True)
class NamespaceInfo:
    """One namespace of the target database and how full it is."""

    namespace: str
    revision: str | None
    runs: int

    def as_dict(self) -> dict[str, object]:
        return {"namespace": self.namespace, "revision": self.revision, "runs": self.runs}


def normalize_namespace(value: str) -> str:
    """The namespace for ``value``, lower-cased and underscored.

    Derived from a file name, so it is the file name that has to lose the
    ``.sqlite`` and anything a schema name cannot carry.
    """
    stem = Path(value).name if value else ""
    for suffix in (".sqlite3", ".sqlite", ".db"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    candidate = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_")
    if not candidate:
        raise DatabaseError(
            f"cannot derive a namespace from {value!r}",
            details={"remedy": "pass --namespace explicitly"},
        )
    return candidate


def validate_namespace(namespace: str) -> str:
    """Reject a namespace that PostgreSQL would not accept as a schema name."""
    if namespace.lower() in RESERVED_NAMESPACES:
        raise DatabaseError(
            f"{namespace!r} is a reserved schema name",
            details={
                "remedy": "choose another --namespace, or --namespace - for the default schema"
            },
        )
    if not NAMESPACE_PATTERN.match(namespace):
        raise DatabaseError(
            f"invalid namespace {namespace!r}: lower case letters, digits and underscores, "
            "starting with a letter, at most 48 characters",
            details={"remedy": "e.g. --namespace knowledge-replay → knowledge_replay"},
        )
    return namespace


def _quote_schema(namespace: str) -> str:
    """A schema name safe to embed in DDL (validated first, so it is bare)."""
    return f'"{namespace}"'


def create_namespace(url: str, namespace: str) -> bool:
    """Create the schema of a namespace. Returns True when it did not exist."""
    engine = create_db_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE SCHEMA IF NOT EXISTS " + _quote_schema(namespace))
            )
    except SQLAlchemyError as exc:
        raise DatabaseError(f"cannot create namespace {namespace!r}: {exc}") from exc
    finally:
        engine.dispose()
    return True


def namespace_is_empty(url: str, namespace: str | None) -> bool:
    """True when the namespace holds no AK-Bench rows yet."""
    engine = create_db_engine(search_path_url(url, namespace))
    try:
        existing = set(inspect(engine).get_table_names())
        if not existing:
            return True
        from akbench.storage.models import Base

        wanted = {table.name for table in Base.metadata.sorted_tables} & existing
        with engine.connect() as connection:
            for name in sorted(wanted):
                count = connection.execute(
                    text(f'SELECT COUNT(*) FROM "{name}"')
                ).scalar_one()
                if count:
                    return False
        return True
    except SQLAlchemyError:
        return True
    finally:
        engine.dispose()


def list_namespaces(url: str) -> list[NamespaceInfo]:
    """Every AK-Bench namespace of the target database, by name."""
    engine = create_db_engine(url)
    found: list[NamespaceInfo] = []
    try:
        with engine.connect() as connection:
            schemas = [
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT schema_name FROM information_schema.schemata "
                        "WHERE schema_name NOT IN ('public', 'information_schema') "
                        "AND schema_name NOT LIKE 'pg_%' ORDER BY 1"
                    )
                )
            ]
            for schema in schemas:
                has_history = connection.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = :schema AND table_name = 'task_runs'"
                    ),
                    {"schema": schema},
                ).scalar()
                if not has_history:
                    continue
                revision = connection.execute(
                    text(f"SELECT version_num FROM {_quote_schema(schema)}.alembic_version")
                ).scalar()
                runs = connection.execute(
                    text(f'SELECT COUNT(*) FROM {_quote_schema(schema)}.task_runs')
                ).scalar_one()
                found.append(NamespaceInfo(schema, revision, int(runs)))
    except SQLAlchemyError as exc:
        raise DatabaseError(f"cannot list the namespaces of the target: {exc}") from exc
    finally:
        engine.dispose()
    return found


def _metadata_tables(wanted: Sequence[str] | None) -> list[Table]:
    """The mapped tables in foreign-key order, the ones the copy may touch."""
    from akbench.storage.models import Base

    available = {table.name: table for table in Base.metadata.sorted_tables}
    if wanted is None:
        return [t for t in Base.metadata.sorted_tables if t.name not in EXCLUDED_TABLES]
    unknown = sorted(set(wanted) - set(available))
    if unknown:
        raise DatabaseError(
            f"unknown tables to copy: {', '.join(unknown)}",
            details={"remedy": "omit the option to copy every mapped table"},
        )
    return [available[name] for name in available if name in set(wanted)]


def _timestamp_columns(table: Table) -> frozenset[str]:
    """Columns PostgreSQL will read as an instant, not a wall-clock text."""
    return frozenset(
        column.name
        for column in table.columns
        if isinstance(column.type, DateTime) and column.type.timezone
    )


def _read_rows(source: Engine, table: Table) -> list[dict[str, object]]:
    """One table as plain rows, with SQLite's naive instants re-anchored to UTC."""
    instants = _timestamp_columns(table)
    columns = list(table.columns.keys())
    rows: list[dict[str, object]] = []
    with source.connect() as connection:
        for record in connection.execute(select(table)):
            row = dict(zip(columns, tuple(record), strict=True))
            for name in instants:
                value = row.get(name)
                if isinstance(value, datetime) and value.tzinfo is None:
                    row[name] = value.replace(tzinfo=UTC)
            rows.append(row)
    return rows


def _reset_sequences(engine: Engine, table: Table) -> bool:
    """Advance one table's sequence past the copied rows.

    Only PostgreSQL has the problem: SQLite numbers rows from the maximum it
    sees. Without this the next inserted row takes the value the sequence was
    left at, which is a primary key the copy already used.
    """
    primary_key = list(table.primary_key.columns) if table.primary_key else []
    if len(primary_key) != 1 or not isinstance(primary_key[0].type, Integer):
        return False
    column = primary_key[0].name
    with engine.begin() as connection:
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:table, :column)"),
            {"table": table.name, "column": column},
        ).scalar()
        if not sequence:
            return False
        highest = connection.execute(text(f'SELECT MAX("{column}") FROM "{table.name}"')).scalar()
        if highest is None:
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), 1, false)"),
                {"sequence": sequence},
            )
        else:
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), :highest, true)"),
                {"sequence": sequence, "highest": int(highest)},
            )
    return True


def _count(engine: Engine, table_name: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one())


def import_sqlite(
    source_url: str,
    target_url: str,
    *,
    namespace: str | None = None,
    replace: bool = False,
    tables: Sequence[str] | None = None,
    batch_rows: int = BATCH_ROWS,
) -> ImportReport:
    """Copy one SQLite history into one namespace of the PostgreSQL database.

    ``namespace`` is ``None`` for the default schema, which is only safe while
    that schema is empty: two histories under one key space is how a history
    becomes a lie.
    """
    if database_path_from_url(source_url) is None and not source_url.startswith("sqlite"):
        raise DatabaseError(
            "the source of an import must be a SQLite database",
            details={"remedy": "pass a sqlite:////path/to/akbench.sqlite URL"},
        )
    if make_url(target_url).get_backend_name() != "postgresql":
        raise DatabaseError(
            "the target of an import must be PostgreSQL",
            details={"remedy": "set database.backend to postgres, or AKBENCH_DB_BACKEND=postgres"},
        )

    source = create_db_engine(source_url)
    existing_source = set(inspect(source).get_table_names())
    selected = [table for table in _metadata_tables(tables) if table.name in existing_source]
    if not selected:
        source.dispose()
        raise DatabaseError(
            f"the source has no AK-Bench tables to copy: {source_url}",
            details={"remedy": "run `akbench init` against the source first"},
        )

    if namespace:
        create_namespace(target_url, namespace)
    elif not replace and not namespace_is_empty(target_url, None):
        source.dispose()
        raise DatabaseError(
            "the default schema already holds history; an import would mix two key spaces",
            details={"remedy": "pass --namespace <name>, or --replace to overwrite it"},
        )

    target = create_db_engine(search_path_url(target_url, namespace))
    copied: list[tuple[str, int]] = []
    try:
        revision_before, _ = upgrade(search_path_url(target_url, namespace))
        created = revision_before is None
        with target.begin() as connection:
            for table in reversed(selected):
                connection.execute(table.delete())
        for table in selected:
            rows = _read_rows(source, table)
            with target.begin() as connection:
                for start in range(0, len(rows), batch_rows):
                    connection.execute(table.insert(), rows[start : start + batch_rows])
            copied.append((table.name, len(rows)))
        for table in selected:
            _reset_sequences(target, table)
        mismatched = [
            f"{name} ({_count(source, name)} rows in the source, {_count(target, name)} here)"
            for name, _ in copied
            if _count(source, name) != _count(target, name)
        ]
        if mismatched:
            raise DatabaseError(
                "the import is incomplete: " + "; ".join(mismatched),
                details={"remedy": "rerun the import; the namespace was not verified"},
            )
    except SQLAlchemyError as exc:
        raise DatabaseError(f"import from {source_url} failed: {exc}") from exc
    finally:
        source.dispose()
        target.dispose()

    return ImportReport(
        source=source_url,
        target=make_url(search_path_url(target_url, namespace)).render_as_string(
            hide_password=True
        ),
        namespace=namespace,
        revision=head_revision(),
        created=created,
        tables=tuple(copied),
    )

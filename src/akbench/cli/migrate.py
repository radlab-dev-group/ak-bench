"""``akbench migrate``: bring a SQLite history into the PostgreSQL database.

The SQLite file was the history of one working directory, so several of them
cannot share one PostgreSQL schema. Each import therefore lands in its own
namespace -- a PostgreSQL schema -- and is read back by naming it
(``AKBENCH__DATABASE__POSTGRES__NAMESPACE=<name>``).

The target is the configured PostgreSQL, so no credential is ever typed on a
command line: connection parameters come from ``.env``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import redact_database_url, resolve_database_url
from akbench.core.errors import DatabaseError
from akbench.storage.importer import (
    import_sqlite,
    list_namespaces,
    namespace_is_empty,
    normalize_namespace,
    validate_namespace,
)

migrate_app = typer.Typer(
    help="Move recorded history into the configured PostgreSQL database.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")


def _source_url(path: str) -> str:
    """A ``sqlite:`` URL for a file that exists and is readable."""
    file = Path(path).expanduser()
    if not file.is_file():
        raise DatabaseError(
            f"no SQLite database at {file}",
            details={"remedy": "pass the path of an akbench.sqlite file"},
        )
    return f"sqlite:///{file.resolve()}"


def _default_namespace(paths: list[str], explicit: str | None) -> str | None:
    if explicit is None:
        if len(paths) > 1:
            raise DatabaseError(
                "several sources need a namespace of their own",
                details={"remedy": "pass --namespace, or import one file at a time"},
            )
        return normalize_namespace(paths[0])
    if explicit in {"", "-"}:
        return None
    return validate_namespace(normalize_namespace(explicit))


@migrate_app.command("sqlite")
@handle_errors
def migrate_sqlite_cmd(
    ctx: typer.Context,
    sources: list[str] = typer.Argument(..., help="SQLite file(s) to import."),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        help="Target namespace (default: derived from the file name). "
        "'-' imports into the default schema.",
    ),
    replace: bool = typer.Option(
        False, "--replace", help="Replace the rows the target namespace already holds."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Import one or more SQLite histories into PostgreSQL, each in its namespace."""
    context: CliContext = ctx.obj
    settings = context.loaded().settings
    target = resolve_database_url(settings)
    if settings.database.backend != "postgres" and not settings.database.url:
        raise DatabaseError(
            "the configured backend is not PostgreSQL",
            details={"remedy": "set database.backend to postgres, or AKBENCH_DB_BACKEND=postgres"},
        )

    chosen = _default_namespace(list(sources), namespace)
    reports = []
    for index, path in enumerate(list(sources)):
        # One namespace per file: two histories under one key space is how a
        # history becomes a lie. Only an explicit '-' shares the default one.
        target_namespace = chosen if len(sources) == 1 else normalize_namespace(path)
        if target_namespace is None and not replace and not namespace_is_empty(target, None):
            raise DatabaseError(
                "the default schema already holds history",
                details={"remedy": "drop --namespace - or pass --replace"},
            )
        report = import_sqlite(
            _source_url(path), target, namespace=target_namespace, replace=replace
        )
        reports.append(report)
        if not as_json:
            suffix = f" ({index + 1}/{len(sources)})" if len(sources) > 1 else ""
            console.print(f"[green]imported[/green] {path} → {report.describe()}{suffix}")

    if as_json:
        show_json([report.as_dict() for report in reports])
        return
    if chosen:
        console.print(
            f"[dim]read it back with "
            f"AKBENCH__DATABASE__POSTGRES__NAMESPACE={reports[-1].namespace}[/dim]"
        )


@migrate_app.command("list")
@handle_errors
def migrate_list_cmd(
    ctx: typer.Context,
    as_json: bool = JSON_OPTION,
) -> None:
    """List the namespaces (imported histories) of the configured database."""
    context: CliContext = ctx.obj
    settings = context.loaded().settings
    target = resolve_database_url(settings)
    found = list_namespaces(target)
    if as_json:
        show_json([info.as_dict() for info in found])
        return
    console.print(f"database: {redact_database_url(target)}")
    if not found:
        console.print("[dim]no namespace with AK-Bench history[/dim]")
        return
    for info in found:
        console.print(f"  {info.namespace:<28} {info.runs:>6} runs   rev {info.revision}")

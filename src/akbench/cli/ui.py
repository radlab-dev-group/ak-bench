"""``akbench ui``: launch real-time interactive benchmark web UI."""

from __future__ import annotations

import os

import typer
import uvicorn

from akbench.cli.common import console, handle_errors
from akbench.config.loader import redact_database_url, resolve_database_url
from akbench.storage.db import namespace_of_url

ui_app = typer.Typer(
    help="Launch the interactive real-time AK-Bench Web UI.",
    no_args_is_help=False,
)


@ui_app.callback(invoke_without_command=True)
@handle_errors
def ui_main_cmd(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind host."),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port."),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload."),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        help="PostgreSQL namespace (an imported history) to show. "
        "Default: the configured one.",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Read another database instead of the configured one.",
    ),
) -> None:
    """Launch the interactive real-time AK-Bench web dashboard.

    The database comes from the project configuration -- the same ``.env`` the
    CLI reads -- so the dashboard shows what ``akbench history`` shows.
    """
    if ctx.invoked_subcommand is not None:
        return

    settings = ctx.obj.loaded().settings
    database = database_url or redact_database_url(resolve_database_url(settings))
    active = (
        namespace_of_url(database_url)
        if database_url
        else settings.database.postgres.namespace
    )
    console.print(
        f"[green]Starting AK-Bench UI on[/green] [bold cyan]http://{host}:{port}[/bold cyan]"
    )
    console.print(f"  [dim]database:[/dim]  {database}")
    if active:
        console.print(f"  [dim]namespace:[/dim] {active}")

    # The options travel as the configuration overrides they stand for, so the
    # server -- and a --reload subprocess -- resolve them exactly once.
    if namespace:
        os.environ["AKBENCH__DATABASE__POSTGRES__NAMESPACE"] = namespace
    if database_url:
        os.environ["AKBENCH__DATABASE__URL"] = database_url
    uvicorn.run("bench_ui.app:app", host=host, port=port, reload=reload)

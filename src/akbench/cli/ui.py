"""``akbench ui``: launch real-time interactive benchmark web UI."""

from __future__ import annotations

import typer
import uvicorn

from akbench.cli.common import console, handle_errors

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
) -> None:
    """Launch the interactive real-time AK-Bench web dashboard."""
    if ctx.invoked_subcommand is not None:
        return

    console.print(
        f"[green]Starting AK-Bench UI on[/green] [bold cyan]http://{host}:{port}[/bold cyan]"
    )
    uvicorn.run("bench_ui.app:app", host=host, port=port, reload=reload)

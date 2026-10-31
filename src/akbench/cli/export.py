"""``akbench export``: write one experiment out as JSON, CSV and HTML.

The export is the reportable form of an experiment: descriptor, pinned
descriptors, variants, runs, metrics, artifacts and the reproducibility
digest of each run, screened for anything that must not leave the machine.
"""

from __future__ import annotations

from pathlib import Path

import typer

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths, resolve_database_url
from akbench.export.exporter import FORMATS, build_export, write_bundle
from akbench.reporting.data import collect_history
from akbench.storage.db import create_db_engine
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import is_initialized

export_app = typer.Typer(
    help="Export an experiment as JSON, CSV and HTML.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")
FORMAT_OPTION = typer.Option(
    None,
    "--format",
    "-f",
    help="Export format (repeatable): json, csv, html. Default: all three.",
)
OUTPUT_OPTION = typer.Option(
    None, "--output", "-o", help="Export directory (default: the configured reports directory)."
)


def _store(context: CliContext) -> HistoryStore:
    settings = context.loaded().settings
    url = resolve_database_url(settings)
    if not is_initialized(url):
        console.print(
            f"[red]the database has no history to export[/red] {url}\n"
            "[dim]run `akbench init`, then record a plan or a run with --store[/dim]"
        )
        raise typer.Exit(1)
    return HistoryStore(create_db_engine(url))


def _output_dir(context: CliContext, output: str | None) -> Path:
    if output:
        return Path(output)
    paths = build_app_paths(context.loaded().settings)
    return paths.reports_dir / "exports"


def _formats(values: list[str] | None) -> tuple[str, ...]:
    if not values:
        return FORMATS
    chosen = tuple(value.strip().lower() for value in values if value.strip())
    unknown = [value for value in chosen if value not in FORMATS]
    if unknown:
        console.print(f"[red]unknown format[/red] {', '.join(unknown)}; available: json, csv, html")
        raise typer.Exit(1)
    return chosen


@export_app.command("experiment")
@handle_errors
def export_experiment_cmd(
    ctx: typer.Context,
    experiment_uid: str = typer.Argument(..., help="Experiment uid to export."),
    fmt: list[str] = FORMAT_OPTION,
    output: str = OUTPUT_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Export one experiment: descriptor, runs, metrics and artifacts."""
    context: CliContext = ctx.obj
    data = collect_history(_store(context))
    if data.experiment(experiment_uid) is None:
        console.print(f"[red]unknown experiment[/red] {experiment_uid}")
        raise typer.Exit(1)

    bundle = build_export(data, experiment_uid)
    target = _output_dir(context, output)
    written = write_bundle(bundle, data, output_dir=target, formats=_formats(fmt))

    if as_json:
        show_json(
            {
                "experiment": experiment_uid,
                "output": str(target),
                "files": [str(path) for path in written],
                "runs": len(bundle.document.get("runs", [])),
                "redactions": bundle.redactions,
            }
        )
        return

    console.print(f"[green]exported[/green] {experiment_uid} to {target}")
    for path in written:
        console.print(f"  {path.name}")
    console.print(f"  runs        {len(bundle.document.get('runs', []))}")
    if bundle.redactions:
        summary = ", ".join(f"{row['kind']} x {row['count']}" for row in bundle.redactions)
        console.print(f"  [yellow]redacted[/yellow] {summary}")
    else:
        console.print("  redactions  none")

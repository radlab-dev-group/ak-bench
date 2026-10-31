"""``akbench`` command line interface.

Implemented here: version, init, doctor, config, descriptor, agent, category and
dataset commands. The remaining commands from the plan (runtime, experiment,
report, export) arrive with their own phases and are intentionally absent rather
than stubbed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.table import Table

from akbench import __version__
from akbench.bootstrap import initialize
from akbench.cli.agents import agent_run_cmd  # noqa: F401 - registers agent run
from akbench.cli.common import (
    EXIT_ERROR,
    EXIT_OK,
    CliContext,
    console,
    handle_errors,
    show_json,
)
from akbench.cli.dataset import dataset_app
from akbench.cli.descriptors import agent_app, category_app, descriptor_app
from akbench.cli.evaluate import evaluate_app
from akbench.cli.experiments import experiment_app
from akbench.cli.knowledge import knowledge_app
from akbench.cli.metrics import metrics_app
from akbench.cli.plugins import plugin_app
from akbench.cli.run import run_app
from akbench.cli.runtime import runtime_app
from akbench.config.loader import build_app_paths, resolve_database_url
from akbench.doctor import CheckStatus, run_diagnostics

app = typer.Typer(
    name="akbench",
    help="AK-Bench: repeatable evaluation of coding agents, LLM routers and plugins.",
    no_args_is_help=True,
    invoke_without_command=True,
    pretty_exceptions_show_locals=False,
)
config_app = typer.Typer(help="Inspect the configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(descriptor_app, name="descriptor")
app.add_typer(dataset_app, name="dataset")
app.add_typer(agent_app, name="agent")
app.add_typer(category_app, name="category")
app.add_typer(runtime_app, name="runtime")
app.add_typer(evaluate_app, name="evaluate")
app.add_typer(experiment_app, name="experiment")
app.add_typer(run_app, name="run")
app.add_typer(plugin_app, name="plugin")
app.add_typer(metrics_app, name="metrics")
app.add_typer(knowledge_app, name="knowledge")

STATUS_MARKS = {
    CheckStatus.OK: "[green]ok[/green]",
    CheckStatus.INFO: "[cyan]info[/cyan]",
    CheckStatus.WARNING: "[yellow]warn[/yellow]",
    CheckStatus.FAIL: "[red]fail[/red]",
}

ConfigOption = typer.Option(
    None,
    "--config",
    "-c",
    exists=False,
    help="Path to a YAML configuration file.",
)
ProjectOption = typer.Option(
    None,
    "--project-root",
    exists=False,
    help="Project root (overrides AKBENCH_HOME and auto-detection).",
)


def _context(
    config: Path | None,
    project_root: Path | None,
    verbose: bool,
    quiet: bool,
) -> CliContext:
    return CliContext(config_path=config, project_root=project_root, verbose=verbose, quiet=quiet)


@app.callback()
def cli(
    ctx: typer.Context,
    config: Path | None = ConfigOption,
    project_root: Path | None = ProjectOption,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log at DEBUG level."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only log errors."),
    version: bool = typer.Option(False, "--version", help="Print the AK-Bench version and exit."),
) -> None:
    if version:
        console.print(f"ak-bench {__version__}")
        raise typer.Exit(EXIT_OK)
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit(EXIT_OK)
    context = _context(config, project_root, verbose, quiet)
    ctx.obj = context
    try:
        context.apply_logging()
    except Exception as exc:  # config problems must not stop `config validate` diagnostics
        typer.echo(f"warning: logging not configured ({exc})", err=True)


@app.command("version")
@handle_errors
def version_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Print the AK-Bench version and key dependency versions."""
    import importlib.metadata as md

    deps = {}
    for name in ("pydantic", "typer", "sqlalchemy", "alembic", "jinja2"):
        try:
            deps[name] = md.version(name)
        except md.PackageNotFoundError:
            deps[name] = None

    payload = {
        "ak_bench": __version__,
        "python": sys.version.split()[0],
        "dependencies": deps,
    }
    if as_json:
        show_json(payload)
        return
    console.print(f"ak-bench {payload['ak_bench']} (python {payload['python']})")
    for name, dep_version in deps.items():
        console.print(f"  {name:<12} {dep_version or 'missing'}")


@app.command("init")
@handle_errors
def init_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
    no_config: bool = typer.Option(False, help="Do not write a configuration file."),
    no_migrate: bool = typer.Option(False, help="Do not apply migrations."),
    force_config: bool = typer.Option(False, help="Overwrite an existing configuration file."),
) -> None:
    """Create directories, configuration and the database (migrations to head)."""
    context: CliContext = ctx.obj
    if as_json:
        context.apply_logging(min_level="WARNING")
    loaded = context.loaded()
    report = initialize(
        loaded,
        write_config=not no_config,
        migrate=not no_migrate,
        force_config=force_config,
    )

    if as_json:
        show_json(report.as_dict())
    else:
        root = build_app_paths(loaded.settings).project_root
        console.print(f"[green]initialized[/green] project at {root}")
        console.print(f"  directories created: {len(report.created_dirs)}")
        if report.config_written:
            console.print(f"  configuration: {report.config_path}")
        else:
            console.print(f"  configuration: unchanged ({report.config_path})")
        console.print(f"  database: {report.schema_summary or 'skipped'}")
        for message in report.messages:
            console.print(f"  [dim]{message}[/dim]")
    raise typer.Exit(EXIT_OK)


@app.command("doctor")
@handle_errors
def doctor_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
    strict: bool = typer.Option(False, help="Treat warnings as errors."),
) -> None:
    """Check environment readiness (Python, packages, directories, database, tools)."""
    context: CliContext = ctx.obj
    report = run_diagnostics(context.loaded())

    if as_json:
        show_json(report.as_dict())
    else:
        table = Table(title="akbench doctor", show_lines=False)
        table.add_column("status", width=6)
        table.add_column("check", overflow="fold")
        table.add_column("detail", overflow="fold")
        table.add_column("hint", overflow="fold", style="dim")
        for check in report.checks:
            table.add_row(STATUS_MARKS[check.status], check.name, check.detail, check.hint or "")
        console.print(table)
        if report.ok:
            console.print("[green]environment ready[/green]")
        else:
            console.print(f"[red]reported errors: {len(report.failed)}[/red]")

    if report.failed or (strict and report.warnings):
        raise typer.Exit(EXIT_ERROR)
    raise typer.Exit(EXIT_OK)


@config_app.command("show")
@handle_errors
def config_show_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
    show_all: bool = typer.Option(
        False, "--all", help="Also show the remaining configuration sections."
    ),
) -> None:
    """Show the effective configuration together with its sources."""
    context: CliContext = ctx.obj
    loaded = context.loaded()
    settings = loaded.settings
    payload = {
        "source": loaded.describe(),
        "config_path": str(loaded.path) if loaded.path else None,
        "settings": settings.model_dump(mode="json"),
        "resolved_paths": build_app_paths(settings).report(),
        "database_url": resolve_database_url(settings),
    }
    if as_json:
        show_json(payload)
        return

    console.print(f"[bold]paths[/bold] (source: {payload['source']})")
    for key, value in payload["resolved_paths"].items():
        console.print(f"  {key:<22} {value}")
    console.print(f"  {'database_url':<22} {payload['database_url']}")
    if show_all:
        console.print("[bold]settings[/bold]")
        for section, values in payload["settings"].items():
            if section == "project_root":
                continue
            console.print(f"  {section}: {values}")


@config_app.command("validate")
@handle_errors
def config_validate_cmd(ctx: typer.Context) -> None:
    """Validate the configuration file; creates no directories."""
    context: CliContext = ctx.obj
    loaded = context.loaded()
    console.print(f"[green]configuration is valid[/green] · {loaded.describe()}")


def main() -> None:  # pragma: no cover - console entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

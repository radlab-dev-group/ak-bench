"""``akbench`` command line interface (Faza 1 scope).

Implemented here: version, init, doctor, config show/validate. The remaining
commands from the plan (agent, dataset, experiment, report, export) arrive with
their own phases and are intentionally absent rather than stubbed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from akbench import __version__
from akbench.bootstrap import initialize
from akbench.cli.common import (
    EXIT_ERROR,
    EXIT_OK,
    CliContext,
    console,
    handle_errors,
    show_json,
)
from akbench.config.loader import build_app_paths, resolve_database_url
from akbench.doctor import CheckStatus, run_diagnostics

app = typer.Typer(
    name="akbench",
    help="AK-Bench: repeatabalna ocena agentow programistycznych, routerow i pluginow.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
config_app = typer.Typer(help="Inspekcja konfiguracji.", no_args_is_help=True)
app.add_typer(config_app, name="config")

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
    help="Sciezka do pliku konfiguracji YAML.",
)
ProjectOption = typer.Option(
    None,
    "--project-root",
    exists=False,
    help="Katalog glowny projektu (nadpisuje AKBENCH_HOME i autowykrywanie).",
)


def _context(config: Optional[Path], project_root: Optional[Path], verbose: bool, quiet: bool) -> CliContext:
    return CliContext(config_path=config, project_root=project_root, verbose=verbose, quiet=quiet)


@app.callback()
def cli(
    ctx: typer.Context,
    config: Optional[Path] = ConfigOption,
    project_root: Optional[Path] = ProjectOption,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Logi w poziomie DEBUG."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Tylko bledy."),
    version: bool = typer.Option(False, "--version", help="Wersja AK-Bench i wyjscie."),
) -> None:
    if version:
        console.print(f"ak-bench {__version__}")
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
    as_json: bool = typer.Option(False, "--json", help="Wynik jako JSON."),
) -> None:
    """Wersja AK-Bench i wersje kluczowych zaleznosci."""
    import importlib.metadata as md

    deps = {}
    for name in ("pydantic", "typer", "sqlalchemy", "alembic", "jinja2"):
        try:
            deps[name] = md.version(name)
        except md.PackageNotFoundError:
            deps[name] = None

    payload = {"ak_bench": __version__, "python": __import__("sys").version.split()[0], "dependencies": deps}
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
    as_json: bool = typer.Option(False, "--json", help="Wynik jako JSON."),
    no_config: bool = typer.Option(False, help="Nie tworz pliku konfiguracji."),
    no_migrate: bool = typer.Option(False, help="Nie stosuj migracji."),
    force_config: bool = typer.Option(False, help="Nadpisz istniejacy plik konfiguracji."),
) -> None:
    """Tworzy katalogi, konfiguracje i baze danych (migracje do head)."""
    context: CliContext = ctx.obj
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
        console.print(f"[green]zainicjalizowano[/green] projekt w {build_app_paths(loaded.settings).project_root}")
        console.print(f"  katalogi utworzone: {len(report.created_dirs)}")
        if report.config_written:
            console.print(f"  konfiguracja: {report.config_path}")
        else:
            console.print(f"  konfiguracja: bez zmian ({report.config_path})")
        console.print(f"  baza danych: {report.schema_summary or 'pominieta'}")
        for message in report.messages:
            console.print(f"  [dim]{message}[/dim]")
    raise typer.Exit(EXIT_OK)


@app.command("doctor")
@handle_errors
def doctor_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Wynik jako JSON."),
    strict: bool = typer.Option(False, help="Traktuj ostrzezenia jak bledy."),
) -> None:
    """Sprawdza gotowosc srodowiska (python, pakiety, katalogi, baza, narzedzia)."""
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
            console.print("[green]srodowisko gotowe[/green]")
        else:
            console.print(f"[red]zgloszone bledy: {len(report.failed)}[/red]")

    if report.failed or (strict and report.warnings):
        raise typer.Exit(EXIT_ERROR)
    raise typer.Exit(EXIT_OK)


@config_app.command("show")
@handle_errors
def config_show_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Wynik jako JSON."),
    show_all: bool = typer.Option(False, "--all", help="Rowniez wartosci niesciezkeowe konfiguracji."),
) -> None:
    """Pokazuje efektywna konfiguracje wraz ze zrodlami."""
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

    console.print(f"[bold]sciezki[/bold] (zrodlo: {payload['source']})")
    for key, value in payload["resolved_paths"].items():
        console.print(f"  {key:<22} {value}")
    console.print(f"  {'database_url':<22} {payload['database_url']}")
    if show_all:
        console.print("[bold]ustawienia[/bold]")
        for section, values in payload["settings"].items():
            if section == "project_root":
                continue
            console.print(f"  {section}: {values}")


@config_app.command("validate")
@handle_errors
def config_validate_cmd(ctx: typer.Context) -> None:
    """Waliduje plik konfiguracji; nie tworzy zadnych katalogow."""
    context: CliContext = ctx.obj
    loaded = context.loaded()
    console.print(f"[green]konfiguracja poprawna[/green] · {loaded.describe()}")


def main() -> None:  # pragma: no cover - console entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

"""``akbench report``: write the static HTML reports of the recorded history.

Every page is built from what the database holds, so the report says how many
runs a number rests on and leaves an unmeasured value unmeasured. Nothing here
runs an agent, contacts a router or recomputes a verdict.

The tree is written under the configured reports directory
(``data/reports`` by default): an index with the dashboard, one page per
experiment and per task, and one page each for agents, runtimes, plugins and
models.
"""

from __future__ import annotations

from pathlib import Path

import typer
from sqlalchemy.engine import Engine

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths, resolve_database_url
from akbench.core.time import utc_now
from akbench.reporting.data import build_experiment_report, build_task_report, collect_history
from akbench.reporting.render import render_experiment, render_task, write_report_tree
from akbench.storage.db import create_db_engine
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import is_initialized

report_app = typer.Typer(
    help="Write static HTML reports of the recorded history.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")
OUTPUT_OPTION = typer.Option(
    None, "--output", "-o", help="Report directory (default: the configured one)."
)


def _store(context: CliContext) -> HistoryStore:
    settings = context.loaded().settings
    url = resolve_database_url(settings)
    if not is_initialized(url):
        console.print(
            f"[red]the database has no history to report[/red] {url}\n"
            "[dim]run `akbench init`, then record a plan or a run with --store[/dim]"
        )
        raise typer.Exit(1)
    engine: Engine = create_db_engine(url)
    return HistoryStore(engine)


def _reports_dir(context: CliContext, output: str | None) -> Path:
    if output:
        return Path(output)
    paths = build_app_paths(context.loaded().settings)
    return paths.reports_dir


def _describe(target: Path, files: list[Path]) -> None:
    console.print(f"[green]wrote[/green] {len(files)} file(s) to {target}")
    index = target / "index.html"
    if index.is_file():
        console.print(f"  open       {index}")


@report_app.command("all")
@handle_errors
def report_all_cmd(
    ctx: typer.Context,
    output: str = OUTPUT_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Write the whole report tree: dashboard, experiments, tasks, comparisons."""
    context: CliContext = ctx.obj
    data = collect_history(_store(context))
    target = _reports_dir(context, output)
    written = write_report_tree(target, data, generated_at=utc_now().isoformat())

    if as_json:
        show_json(
            {
                "output": str(target),
                "files": [str(path) for path in written],
                "experiments": len(data.experiments),
                "runs": len(data.runs),
                "tasks": len(data.tasks),
            }
        )
        return
    _describe(target, written)
    console.print(
        f"  history    {len(data.experiments)} experiment(s), {len(data.runs)} run(s), "
        f"{len(data.tasks)} task(s)"
    )


@report_app.command("experiment")
@handle_errors
def report_experiment_cmd(
    ctx: typer.Context,
    experiment_uid: str = typer.Argument(..., help="Experiment uid, e.g. knowledge-on-off@1.0.0."),
    output: str = OUTPUT_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Write the report of one experiment."""
    context: CliContext = ctx.obj
    store = _store(context)
    data = collect_history(store)
    if data.experiment(experiment_uid) is None:
        console.print(f"[red]unknown experiment[/red] {experiment_uid}")
        raise typer.Exit(1)

    target = _reports_dir(context, output)
    report = build_experiment_report(data, experiment_uid)
    page = target / "experiments" / experiment_uid / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    document = render_experiment(report, generated_at=utc_now().isoformat())
    page.write_text(
        document.replace("{{css}}", "../../assets/style.css").replace("{{root}}", "../../"),
        encoding="utf-8",
    )

    if as_json:
        show_json({"experiment": experiment_uid, "report": str(page), "runs": len(report.runs)})
        return
    console.print(f"[green]wrote[/green] {page}")
    console.print(f"  runs       {len(report.runs)}")


@report_app.command("task")
@handle_errors
def report_task_cmd(
    ctx: typer.Context,
    task_uid: str = typer.Argument(..., help="Task uid, e.g. wordcount-001@1.0.0."),
    output: str = OUTPUT_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Write the report of one task: every run of it, whichever experiment it came from."""
    context: CliContext = ctx.obj
    store = _store(context)
    data = collect_history(store)
    if data.task(task_uid) is None:
        console.print(f"[red]unknown task[/red] {task_uid}")
        raise typer.Exit(1)

    target = _reports_dir(context, output)
    report = build_task_report(data, task_uid)
    page = target / "tasks" / task_uid / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    document = render_task(report, generated_at=utc_now().isoformat())
    page.write_text(
        document.replace("{{css}}", "../../assets/style.css").replace("{{root}}", "../../"),
        encoding="utf-8",
    )

    if as_json:
        show_json({"task": task_uid, "report": str(page), "runs": len(report.runs)})
        return
    console.print(f"[green]wrote[/green] {page}")
    console.print(f"  runs       {len(report.runs)}")

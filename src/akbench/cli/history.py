"""``akbench history``: read the experiment history back out of the database.

Everything the other commands write lands here. The commands are read-only on
purpose: history is recorded by running experiments and recorded runs, not by
editing rows.

Two of them are worth calling out:

- ``metrics`` prints the availability of every aggregate next to its mean, so
  an average over two of ten runs is not read as one over ten;
- ``verify`` re-checksums a run's artifacts against what was recorded, which
  is the difference between a history and a story about the past.
"""

from __future__ import annotations

import typer
from rich.table import Table
from sqlalchemy.engine import Engine

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import resolve_database_url
from akbench.storage.db import create_db_engine
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import is_initialized

history_app = typer.Typer(
    help="Read the recorded history of experiments, runs and metrics.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")

STATUS_COLORS = {
    "completed": "green",
    "failed": "red",
    "timeout": "yellow",
    "cancelled": "yellow",
    "infrastructure_error": "magenta",
    "evaluation_error": "magenta",
    "invalid_configuration": "magenta",
    "pending": "dim",
}
VERDICT_COLORS = {
    "passed": "green",
    "partial": "yellow",
    "failed": "red",
    "regression": "red",
    "timeout": "yellow",
}


def _store(context: CliContext) -> HistoryStore:
    """Open the history store, or explain why it is not available."""
    settings = context.loaded().settings
    url = resolve_database_url(settings)
    if not is_initialized(url):
        console.print(
            f"[red]the database has no history yet[/red] {url}\n"
            "[dim]run `akbench init` to create and migrate it[/dim]"
        )
        raise typer.Exit(1)
    return HistoryStore(create_db_engine(url))


def _store_from_engine(engine: Engine) -> HistoryStore:
    return HistoryStore(engine)


@history_app.command("experiments")
@handle_errors
def history_experiments_cmd(ctx: typer.Context, as_json: bool = JSON_OPTION) -> None:
    """List recorded experiments with their run counts and verdicts."""
    context: CliContext = ctx.obj
    experiments = _store(context).experiments()

    if as_json:
        show_json(experiments)
        return
    if not experiments:
        console.print("[dim]no experiments recorded[/dim]")
        return
    table = Table(title="Experiments")
    table.add_column("uid", style="cyan")
    table.add_column("type")
    table.add_column("descriptor")
    table.add_column("runs", justify="right")
    table.add_column("verdicts")
    for row in experiments:
        verdicts = ", ".join(
            f"[{VERDICT_COLORS.get(key, 'white')}]{key}[/] {value}"
            for key, value in sorted(row["verdicts"].items())
        )
        table.add_row(
            row["uid"],
            row["type"] or "—",
            row["descriptor"] or "—",
            str(row["runs"]),
            verdicts or "—",
        )
    console.print(table)


@history_app.command("runs")
@handle_errors
def history_runs_cmd(
    ctx: typer.Context,
    experiment: str | None = typer.Argument(None, help="Experiment uid (default all runs)."),
    as_json: bool = JSON_OPTION,
) -> None:
    """List recorded runs, optionally for one experiment."""
    context: CliContext = ctx.obj
    runs = _store(context).runs(experiment)

    if as_json:
        show_json(runs)
        return
    if not runs:
        console.print("[dim]no runs recorded[/dim]")
        return
    table = Table(title=f"Runs ({experiment or 'all'})")
    table.add_column("run", style="cyan", overflow="fold")
    table.add_column("task", overflow="fold")
    table.add_column("status")
    table.add_column("verdict")
    table.add_column("score", justify="right")
    table.add_column("tokens", justify="right")
    for row in runs:
        status = row["status"]
        verdict = (row["evaluation"] or {}).get("verdict")
        tokens = (row["observations"] or {}).get("total_tokens")
        score = (row["evaluation"] or {}).get("score")
        table.add_row(
            row["uid"],
            row["task_uid"] or "—",
            f"[{STATUS_COLORS.get(status, 'white')}]{status}[/]",
            f"[{VERDICT_COLORS.get(str(verdict), 'white')}]{verdict}[/]" if verdict else "—",
            f"{score:.2f}" if isinstance(score, (int, float)) else "—",
            str(tokens) if tokens is not None else "—",
        )
    console.print(table)


@history_app.command("show")
@handle_errors
def history_show_cmd(
    ctx: typer.Context,
    run_uid: str = typer.Argument(..., help="Run uid."),
    as_json: bool = JSON_OPTION,
) -> None:
    """One run with its evaluation, observations, plugins and artifacts."""
    context: CliContext = ctx.obj
    row = _store(context).run(run_uid)
    if row is None:
        console.print(f"[red]unknown run[/red] {run_uid}")
        raise typer.Exit(1)
    events = _store(context).events(run_uid)

    if as_json:
        show_json({**row, "events": events})
        return

    status = row["status"]
    console.print(f"[bold]{row['uid']}[/]")
    console.print(f"  status    [{STATUS_COLORS.get(status, 'white')}]{status}[/]")
    for label, key in (("task", "task_uid"), ("variant", "variant_uid"), ("agent", "agent")):
        if row.get(key):
            console.print(f"  {label:<9} {row[key]}")
    evaluation = row["evaluation"]
    if evaluation:
        verdict = evaluation.get("verdict")
        console.print(
            f"  verdict   [{VERDICT_COLORS.get(str(verdict), 'white')}]{verdict}[/]"
            + (
                f" · {evaluation.get('passed')}/{evaluation.get('total')} tests"
                if evaluation.get("total") is not None
                else ""
            )
        )
    observations = row["observations"]
    if observations:
        console.print(
            f"  usage     tokens={observations.get('total_tokens')} "
            f"tool_calls={observations.get('tool_call_count')}"
        )
    if row["plugins"]:
        console.print(f"  plugins   {', '.join(row['plugins'])}")
    for artifact in row["artifacts"]:
        console.print(
            f"  artifact  {artifact['kind']:<16} {artifact['checksum'][7:19]} {artifact['path']}"
        )
    if row["manifest_digest"]:
        console.print(f"  manifest  {row['manifest_digest']}")
    if events:
        console.print(f"\n  [bold]{len(events)} event(s)[/bold]")
        for event in events[-12:]:
            console.print(
                f"    {event['at'] or '—'}  {event['event_type']:<22} {event['message'] or ''}"
            )


@history_app.command("metrics")
@handle_errors
def history_metrics_cmd(
    ctx: typer.Context,
    experiment: str = typer.Argument(..., help="Experiment uid."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Aggregated metrics of a recorded experiment, with their availability."""
    context: CliContext = ctx.obj
    store = _store(context)
    rows = store.metrics(experiment)

    if as_json:
        show_json({"experiment": experiment, "metrics": rows})
        return
    if not rows:
        console.print(
            f"[dim]no metrics recorded for {experiment}[/dim] "
            "(aggregate them when the runs are stored)"
        )
        return
    table = Table(title=f"Metrics ({experiment})")
    table.add_column("metric", style="cyan")
    table.add_column("group")
    table.add_column("mean", justify="right")
    table.add_column("dev", justify="right")
    table.add_column("min", justify="right")
    table.add_column("max", justify="right")
    table.add_column("measured", justify="right")
    table.add_column("why not", overflow="fold")
    for row in sorted(rows, key=lambda item: (item.get("group") or "", item["metric"])):
        console_value = "—" if row["mean"] is None else f"{row['mean']:g}"
        table.add_row(
            row["metric"],
            row["group"] or "—",
            console_value,
            "—" if row["deviation"] is None else f"{row['deviation']:g}",
            "—" if row["min"] is None else f"{row['min']:g}",
            "—" if row["max"] is None else f"{row['max']:g}",
            f"{row['measured']}/{row['runs']}",
            "[dim]" + (row["unavailable_reason"] or "")[:100] + "[/dim]"
            if row["unavailable_reason"]
            else "—",
        )
    console.print(table)


@history_app.command("verify")
@handle_errors
def history_verify_cmd(
    ctx: typer.Context,
    run_uid: str = typer.Argument(..., help="Run uid whose artifacts should be checked."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Re-checksum a run's artifacts against the history.

    A mismatch is reported and the command exits non-zero: a run whose
    artifacts changed is no longer the run that was measured.
    """
    context: CliContext = ctx.obj
    results = _store(context).verify_artifacts(run_uid)

    if as_json:
        show_json({"run": run_uid, "artifacts": results})
    else:
        if not results:
            console.print(f"[dim]no artifacts recorded for {run_uid}[/dim]")
        for item in results:
            color = "green" if item["ok"] else "red"
            detail = "" if item["ok"] else f" — {item['reason']}"
            console.print(
                f"  [{color}]{'ok' if item['ok'] else 'BROKEN'}[/] {item['kind']:<16} "
                f"{item['path']}{detail}"
            )
    raise typer.Exit(0 if all(item["ok"] for item in results) else 1)

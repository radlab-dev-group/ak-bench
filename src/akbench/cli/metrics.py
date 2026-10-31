"""``akbench metrics``: the metric catalog and the metrics of recorded runs.

The catalog subcommand answers "which metrics exist and which can be computed
here" straight from the Metric Descriptors. The run subcommand reads run
records written by ``akbench run`` and reports what was measured, what was not,
and why — a metric without data stays unavailable instead of becoming zero.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths
from akbench.metrics import MetricCatalog, aggregate_runs, baseline_deltas, collect_run_metrics
from akbench.metrics.aggregate import INTERPRETATION_NOTE

metrics_app = typer.Typer(
    help="Inspect the metric catalog and the metrics of recorded runs.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")
GroupOption = typer.Option(None, "--group", "-g", help="Filter by metric group.")

AVAILABILITY_COLORS = {"computed": "green", "derived": "cyan", "unavailable": "dim"}
GROUP_ORDER = ("quality", "efficiency", "agent_runtime", "knowledge", "reliability")


def _catalog(context: CliContext) -> MetricCatalog:
    paths = build_app_paths(context.loaded().settings)
    return MetricCatalog.load(paths.descriptors_dir)


def _load_record(path: Path) -> dict[str, object]:
    """Read one run record (a mapping, or a list of mappings)."""
    if not path.is_file():
        console.print(f"[red]run record not found[/red] {path}")
        raise typer.Exit(1)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        console.print(f"[red]run record is not valid JSON[/red] {path}: {exc}")
        raise typer.Exit(1) from exc
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return {"runs": payload}
    console.print(f"[red]run record must be an object or a list of objects[/red] {path}")
    raise typer.Exit(1)


def _records(paths: list[str]) -> list[dict[str, object]]:
    if not paths:
        console.print("[red]no run record given[/red] pass one or more run_record.json files")
        raise typer.Exit(1)
    return [_load_record(Path(path)) for path in paths]


def _run_records(record: dict[str, object]) -> list[dict[str, object]]:
    """One record, or the ``runs`` list of an export."""
    runs = record.get("runs")
    if isinstance(runs, list):
        return [run for run in runs if isinstance(run, dict)]
    return [record]


def _collect(record: dict[str, object], catalog: MetricCatalog) -> dict[str, object]:
    observations = record.get("observations")
    return collect_run_metrics(
        record,
        catalog,
        observations=observations if isinstance(observations, dict) else None,
    )


@metrics_app.command("catalog")
@handle_errors
def metrics_catalog_cmd(
    ctx: typer.Context,
    group: str | None = GroupOption,
    as_json: bool = JSON_OPTION,
) -> None:
    """List the metric catalog with the availability of every metric."""
    context: CliContext = ctx.obj
    catalog = _catalog(context)
    descriptors = catalog.by_group(group) if group else catalog.all()
    if group and not descriptors:
        console.print(f"[red]unknown metric group[/red] {group}")
        raise typer.Exit(1)

    if as_json:
        show_json(
            {
                metric.id: {
                    "title": metric.title,
                    "group": metric.metric.group.value,
                    "unit": metric.metric.unit,
                    "direction": metric.metric.direction.value,
                    "availability": metric.metric.availability.value,
                    "requires": list(metric.metric.requires),
                    "unavailable_reason": metric.metric.unavailable_reason,
                }
                for metric in descriptors
            }
        )
        return

    table = Table(title="Metric catalog")
    table.add_column("metric", style="cyan")
    table.add_column("group")
    table.add_column("unit")
    table.add_column("direction")
    table.add_column("availability")
    table.add_column("requires / reason", overflow="fold")
    for metric in sorted(descriptors, key=lambda item: (item.metric.group.value, item.id)):
        body = metric.metric
        table.add_row(
            metric.id,
            body.group.value,
            body.unit or "—",
            body.direction.value,
            f"[{AVAILABILITY_COLORS.get(body.availability.value, 'white')}]"
            f"{body.availability.value}[/]",
            body.unavailable_reason or ", ".join(body.requires) or "—",
        )
    console.print(table)
    console.print(
        f"  {len(catalog.computable())} computable, {len(catalog.unavailable())} unavailable "
        "(an unavailable metric is never reported as zero)"
    )


@metrics_app.command("run")
@handle_errors
def metrics_run_cmd(
    ctx: typer.Context,
    records: list[str] = typer.Argument(None, help="Run record JSON file(s)."),
    baseline: list[str] = typer.Option(
        [], "--baseline", help="Baseline run record(s), for the plan's delta formulas."
    ),
    group: str | None = GroupOption,
    as_json: bool = JSON_OPTION,
) -> None:
    """Collect and aggregate the metrics of recorded runs."""
    context: CliContext = ctx.obj
    catalog = _catalog(context)

    runs: list[dict[str, object]] = []
    for path in _records(records):
        runs.extend(_run_records(path))
    if not runs:
        console.print("[red]no runs found in the given record(s)[/red]")
        raise typer.Exit(1)

    collected = [_collect(run, catalog) for run in runs]
    aggregate = aggregate_runs(collected)
    if group:
        aggregate = {name: item for name, item in aggregate.items() if item.group == group}

    baseline_aggregate = None
    if baseline:
        baseline_runs: list[dict[str, object]] = []
        for path in _records(baseline):
            baseline_runs.extend(_run_records(path))
        baseline_aggregate = aggregate_runs([_collect(run, catalog) for run in baseline_runs])

    deltas = baseline_deltas(aggregate, baseline_aggregate) if baseline_aggregate else []

    if as_json:
        show_json(
            {
                "runs": len(runs),
                "metrics": {name: item.as_dict() for name, item in aggregate.items()},
                "deltas": [delta.as_dict() for delta in deltas],
                "interpretation": INTERPRETATION_NOTE if deltas else None,
            }
        )
        return

    table = Table(title=f"Run metrics ({len(runs)} run(s))")
    table.add_column("metric", style="cyan")
    table.add_column("group")
    table.add_column("value", justify="right")
    table.add_column("min", justify="right")
    table.add_column("max", justify="right")
    table.add_column("measured", justify="right")
    table.add_column("why not", overflow="fold")
    for name in sorted(aggregate, key=lambda key: (GROUP_ORDER.index(aggregate[key].group), key)):
        item = aggregate[name]
        reasons = "; ".join(item.reasons) if item.reasons else "—"
        value = "—" if item.mean is None else f"{item.mean:g}"
        shown_values = [entry for entry in item.values if isinstance(entry, str)]
        if item.mean is None and shown_values:
            value = ", ".join(sorted(set(shown_values))[:3])
        table.add_row(
            name,
            item.group,
            value,
            "—" if item.minimum is None else f"{item.minimum:g}",
            "—" if item.maximum is None else f"{item.maximum:g}",
            f"{item.measured}/{item.runs}",
            "[dim]" + reasons[:120] + "[/dim]" if reasons != "—" else "—",
        )
    console.print(table)

    if deltas:
        console.print("\n[bold]Comparison with baseline[/bold]")
        for delta in deltas:
            if delta.value is None:
                continue
            console.print(
                f"  {delta.delta:<28} {delta.value:+g}  [dim]({delta.formula}; "
                f"variant {delta.variant_value}, baseline {delta.baseline_value})[/dim]"
            )
        console.print(f"  [dim]{INTERPRETATION_NOTE}[/dim]")

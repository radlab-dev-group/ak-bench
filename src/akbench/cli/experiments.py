"""``akbench experiment``: validate and plan experiments without running them.

Plan (section 12.2) is a separate step from execution on purpose: a plan states
how many tasks, variants, repetitions and runs an experiment implies, and that
cost has to be readable before an agent is started. The commands here therefore
touch no workspace, no agent and no network — they read descriptors and the
dataset, and they report.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths, resolve_database_url
from akbench.datasets import Dataset, TaskLoadError
from akbench.descriptors import (
    DescriptorKind,
    DescriptorRegistry,
    LoadedDescriptor,
    load_registry,
)
from akbench.evaluators.registry import default_registry
from akbench.experiments import (
    ExperimentPlan,
    ExperimentPlanner,
    ExperimentValidationError,
    LoadedExperiment,
    load_experiment_directory,
    load_experiment_file,
)
from akbench.experiments.validation import ValidationReport
from akbench.metrics.catalog import MetricCatalog
from akbench.storage.db import create_db_engine
from akbench.storage.history import HistoryStore
from akbench.storage.migrator import upgrade

experiment_app = typer.Typer(
    help="Validate and plan experiment definitions.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")
DEFAULT_EXPERIMENT_DIR = "configs/experiments"

SEVERITY_COLORS = {"error": "red", "warning": "yellow"}


def _planner(context: CliContext) -> ExperimentPlanner:
    paths = build_app_paths(context.loaded().settings)
    descriptors = load_registry(paths.descriptors_dir)
    try:
        dataset = Dataset.load(paths.datasets_dir, base_dir=paths.project_root)
    except TaskLoadError as exc:
        console.print(f"[red]dataset is not usable[/red] {exc}")
        raise typer.Exit(1) from exc
    implemented = {name for name, _version in default_registry().entries()}
    return ExperimentPlanner(
        descriptors=descriptors,
        dataset=dataset,
        datasets_dir=paths.datasets_dir,
        implemented_evaluators=implemented,
    )


def _load_targets(paths: list[str] | None) -> list[LoadedExperiment]:
    """Load files or directories given on the command line, or the default directory."""
    targets = [Path(item) for item in paths] if paths else [Path(DEFAULT_EXPERIMENT_DIR)]
    loaded: list[LoadedExperiment] = []
    for target in targets:
        if target.is_dir():
            found = load_experiment_directory(target)
            if not found:
                console.print(f"[yellow]no experiment files in[/yellow] {target}")
            loaded.extend(found)
        elif target.is_file():
            loaded.append(load_experiment_file(target))
        else:
            console.print(f"[red]experiment path not found[/red] {target}")
            raise typer.Exit(1)
    if not loaded:
        console.print(
            f"[red]no experiment to inspect[/red] expected YAML files under "
            f"{DEFAULT_EXPERIMENT_DIR}"
        )
        raise typer.Exit(1)
    return loaded


def _print_issues(report: ValidationReport, indent: str = "  ") -> None:
    for issue in report.issues:
        color = SEVERITY_COLORS.get(issue.severity.value, "white")
        console.print(f"{indent}[{color}]{issue.severity.value}[/{color}] {issue.message}")


@experiment_app.command("list")
@handle_errors
def experiment_list_cmd(ctx: typer.Context, as_json: bool = JSON_OPTION) -> None:
    """List the experiment definitions this project ships."""
    context: CliContext = ctx.obj
    paths = build_app_paths(context.loaded().settings)
    directory = paths.project_root / DEFAULT_EXPERIMENT_DIR
    loaded = load_experiment_directory(directory)

    if as_json:
        show_json([item.as_dict() for item in loaded])
        return
    if not loaded:
        console.print(f"[dim]no experiment files under {directory}[/dim]")
        return
    table = Table(title=f"Experiments ({directory})")
    table.add_column("id", style="cyan")
    table.add_column("version")
    table.add_column("type")
    table.add_column("agent")
    table.add_column("strategy")
    table.add_column("title")
    for item in loaded:
        body = item.descriptor.experiment
        table.add_row(
            item.descriptor.id,
            item.descriptor.version,
            body.type.value,
            body.agent.id,
            body.factors.strategy.value,
            item.descriptor.title or "",
        )
    console.print(table)


@experiment_app.command("validate")
@handle_errors
def experiment_validate_cmd(
    ctx: typer.Context,
    paths: list[str] = typer.Argument(None, help="Experiment files or directories."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Validate experiment definitions; exit 1 when one is not runnable."""
    planner = _planner(ctx.obj)
    loaded_experiments = _load_targets(paths)

    results: list[dict[str, object]] = []
    failed = False
    for item in loaded_experiments:
        report = planner.validate(item)
        results.append({**item.as_dict(), "validation": report.as_dict()})
        if not report.ok:
            failed = True
        if as_json:
            continue
        color = "green" if report.ok else "red"
        mark = "ok" if report.ok else "invalid"
        console.print(f"[{color}]{mark}[/] {item.identity}")
        _print_issues(report)

    if as_json:
        show_json(results)
    raise typer.Exit(1 if failed else 0)


@experiment_app.command("plan")
@handle_errors
def experiment_plan_cmd(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="Experiment file to plan."),
    show_variants: bool = typer.Option(
        False, "--variants", help="List every variant, not only the matrix size."
    ),
    store_plan: bool = typer.Option(
        False,
        "--store",
        help="Record the plan (experiment, variants, pinned descriptors) in the history.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Expand an experiment into tasks, variants and runs."""
    context: CliContext = ctx.obj
    planner = _planner(context)
    experiment = load_experiment_file(Path(path))

    try:
        plan = planner.plan(experiment)
    except ExperimentValidationError as exc:
        console.print(f"[red]experiment is not runnable[/red] {exc}")
        for issue in exc.details.get("issues", []):
            console.print(f"  [red]error[/red] {issue['message']}")
        raise typer.Exit(1) from exc

    payload = plan.as_dict()
    if store_plan:
        payload["stored"] = _store_plan(
            context, plan, load_registry(build_app_paths(context.loaded().settings).descriptors_dir)
        )

    if as_json:
        show_json(payload)
        return

    if store_plan:
        stored = payload["stored"]
        console.print(
            f"  [green]stored[/green] {stored['experiment_uid']} "
            f"({stored['variants']} variants, {stored['snapshots']} snapshots, "
            f"{stored['metrics']} metrics)"
        )

    counts = plan.counts
    console.print(f"[cyan]plan[/] {plan.experiment.identity}")
    console.print(f"  agent        {plan.agent_id} ({plan.mode}"
                  f"{', runtime ' + plan.runtime_id if plan.runtime_id else ''})")
    console.print(f"  strategy     {plan.experiment.descriptor.experiment.factors.strategy.value}")
    console.print(
        f"  size         {counts.tasks} tasks x {counts.variants} variants x "
        f"{counts.repetitions} repetitions = [bold]{counts.runs} runs[/bold]"
    )
    console.print(f"  cost         {plan.estimate.basis}")
    if plan.estimate.total_seconds_upper_bound is not None:
        console.print(f"               upper bound "
                      f"{plan.estimate.total_seconds_upper_bound / 3600:.2f} h")
    if plan.factors:
        console.print("  factors")
        for factor in plan.factors:
            console.print(f"    {factor.id} {list(factor.values)}")
    if plan.tasks:
        console.print("  tasks        " + ", ".join(task.uid for task in plan.tasks))
    if show_variants:
        console.print("  variants")
        for variant in plan.variants:
            mark = " (baseline)" if variant.is_baseline else ""
            values = ", ".join(f"{key}={value}" for key, value in variant.values.items())
            console.print(f"    {variant.variant_id} {values or '(reference)'}{mark}")
    for warning in plan.validation.warnings:
        console.print(f"  [yellow]warning[/yellow] {warning.message}")


def _snapshot_payload(entry: LoadedDescriptor) -> dict[str, object]:
    """One pinned descriptor in the shape :meth:`HistoryStore.record_plan` wants."""
    snapshot = entry.snapshot
    return {
        "kind": snapshot.kind.value,
        "id": snapshot.id,
        "version": snapshot.version,
        "digest": snapshot.digest,
        "source": snapshot.source,
        "payload": snapshot.payload,
    }


def _pinned_descriptors(
    descriptors: DescriptorRegistry, plan: ExperimentPlan
) -> list[LoadedDescriptor]:
    """Resolve the descriptors a plan pinned, keeping the exact versions it used."""
    entries: list[LoadedDescriptor] = []
    wanted: list[tuple[DescriptorKind, str]] = [(DescriptorKind.AGENT, plan.agent_id)]
    if plan.runtime_id:
        wanted.append((DescriptorKind.RUNTIME, plan.runtime_id))
    for kind, identity in wanted:
        entry = descriptors.get(kind, identity)
        if entry is not None:
            entries.append(entry)
    for pinned in plan.descriptor_snapshots:
        kind_part, _, rest = pinned.partition(":")
        try:
            kind = DescriptorKind(kind_part)
        except ValueError:
            continue
        entry = descriptors.get(kind, rest)
        if entry is not None and entry not in entries:
            entries.append(entry)
    return entries


def _metric_rows(
    catalog: MetricCatalog, metric_ids: list[str]
) -> dict[str, dict[str, object]]:
    """Catalog rows for the metrics an experiment declares, version included."""
    rows: dict[str, dict[str, object]] = {}
    for metric_id in metric_ids:
        if not catalog.has(metric_id):
            continue
        descriptor = catalog.get(metric_id)
        rows[metric_id] = {**catalog.as_dict()[metric_id], "version": descriptor.version}
    return rows


def _store_plan(
    context: CliContext, plan: ExperimentPlan, descriptors: DescriptorRegistry
) -> dict[str, object]:
    """Record a plan as history: experiment, variants, pinned descriptors, metrics.

    A plan is stored because a run that was never planned is not reproducible:
    the variants and the descriptor versions are what make a result mean
    something after the configuration has moved on.
    """
    settings = context.loaded().settings
    url = resolve_database_url(settings)
    upgrade(url)
    store = HistoryStore(create_db_engine(url))

    experiment = plan.experiment
    body = experiment.descriptor.experiment
    stored = store.record_plan(
        experiment_uid=experiment.identity,
        title=experiment.descriptor.title,
        experiment_type=body.type.value,
        descriptor_id=experiment.descriptor.id,
        descriptor_version=experiment.descriptor.version,
        config_hash=experiment.digest,
        variants=[
            {
                "uid": variant.variant_id,
                "index": variant.index,
                "values": variant.values,
                "agent_config": variant.agent_config,
                "environment_requests": variant.environment_requests,
                "applies": variant.applies,
                "config_hash": variant.config_hash,
                "is_baseline": variant.is_baseline,
            }
            for variant in plan.variants
        ],
        snapshots=[_snapshot_payload(entry) for entry in _pinned_descriptors(descriptors, plan)],
    )
    catalog = MetricCatalog.from_registry(descriptors)
    metrics = store.record_metric_catalog(_metric_rows(catalog, body.metrics))
    store.record_events(
        [
            {
                "event_type": "planned",
                "message": (
                    f"{plan.counts.runs} runs: {plan.counts.tasks} tasks x "
                    f"{plan.counts.variants} variants x "
                    f"{plan.counts.repetitions} repetitions"
                ),
            }
        ],
        experiment_uid=experiment.identity,
    )
    return {
        "experiment_uid": stored["uid"],
        "variants": len(plan.variants),
        "snapshots": len(plan.descriptor_snapshots),
        "metrics": metrics,
    }

"""``akbench experiment``: validate and plan experiments without running them.

Plan (section 12.2) is a separate step from execution on purpose: a plan states
how many tasks, variants, repetitions and runs an experiment implies, and that
cost has to be readable before an agent is started. The commands here therefore
touch no workspace, no agent and no network — they read descriptors and the
dataset, and they report.
"""

from __future__ import annotations

import hashlib
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.table import Table

from akbench.agents.catalog import build_agent_registry
from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.cli.records import store_run, write_record
from akbench.cli.timing import (
    StepClock,
    format_clock,
    format_duration,
    format_phases,
    phase_durations,
)
from akbench.config.loader import build_app_paths, resolve_database_url
from akbench.datasets import Dataset, RepositoryManager, TaskLoadError, WorkspaceManager
from akbench.descriptors import (
    AgentDescriptor,
    DescriptorKind,
    DescriptorRegistry,
    LoadedDescriptor,
    RuntimeDescriptor,
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
from akbench.orchestration import OrchestrationConfig, RunOrchestrator, RunState
from akbench.orchestration.cancellation import (
    CancelToken,
    FileCancelSource,
    cancel_marker_path,
    install_cancellation_handlers,
)
from akbench.orchestration.lifecycle import TERMINAL_STATES
from akbench.runtime import build_runtime_registry
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

STATE_COLORS = {
    "completed": "green",
    "failed": "red",
    "timeout": "yellow",
    "cancelled": "yellow",
    "infrastructure_error": "magenta",
    "invalid_configuration": "magenta",
    "evaluation_error": "magenta",
}


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
            if variant.runtime_env:
                declared = ", ".join(
                    f"{name}={value}" for name, value in sorted(variant.runtime_env.items())
                )
                console.print(f"      runtime starts with {declared}")
    for warning in plan.validation.warnings:
        console.print(f"  [yellow]warning[/yellow] {warning.message}")


def _agent_registry(context: CliContext):
    paths = build_app_paths(context.loaded().settings)
    registry = load_registry(paths.descriptors_dir)
    return build_agent_registry(
        [
            entry.descriptor
            for entry in registry.entries(DescriptorKind.AGENT)
            if isinstance(entry.descriptor, AgentDescriptor)
        ],
        allow_missing_adapter=True,
    )


def _runtime_registry(context: CliContext):
    paths = build_app_paths(context.loaded().settings)
    registry = load_registry(paths.descriptors_dir)
    return build_runtime_registry(
        [
            entry.descriptor
            for entry in registry.entries(DescriptorKind.RUNTIME)
            if isinstance(entry.descriptor, RuntimeDescriptor)
        ],
        allow_missing_adapter=True,
    )


def _knowledge_workspace_id(
    experiment,
    *,
    agent_id: str,
    task_uid: str,
    variant_id: str,
    repetition: int,
    repository_source: str,
) -> str | None:
    """Pin a memory run's checkout to the repository name the plugin scopes by.

    A ``knowledge_replay`` experiment is only honest when the replay arm can
    read what the learning arm wrote. The knowledge plugin decides that with
    one fact about the request: the *basename* of the working directory the
    agent declares, which for a checkout is the name of its directory.
    AK-Bench workspaces are named after the run, so two runs of the same
    fixture — let alone two runs of two tasks of one fixture — land in two
    collections and a replay silently reads nothing.

    The pin is therefore the basename, not the path: the workspace id becomes
    ``<run slug>/<repository name>``, unique per run because the slug is, and
    the same for every arm that works the same fixture because the name is.
    An operator who cannot let the harness name the checkout sets the
    plugin's own ``scope.overrides`` table instead; the two ways are
    documented in ``docs/KNOWLEDGE_REPLAY.md``.
    """
    body = experiment.descriptor.experiment
    if body.knowledge is None:
        return None
    slug = _run_slug(agent_id, task_uid, variant_id, repetition)
    name = Path(str(repository_source)).name
    if not name:
        return None
    return f"{slug}/{name}"


def _environment_snapshot(experiment: LoadedExperiment, registry: DescriptorRegistry) -> dict:
    """The environment a run declares it executed in, as the record states it.

    The experiment names an environment by id; the run records its identity,
    its sandbox kind and the digest of the descriptor behind it. A run with no
    declared environment records nothing rather than guessing the host, because
    a manifest that invents a fact is worse than one that admits the gap.
    """
    selection = experiment.descriptor.experiment.environment
    if selection is None:
        return {}
    entry = registry.get(DescriptorKind.ENVIRONMENT, selection.id, selection.version)
    if entry is None:  # the planner rejects it; a run never gets this far
        return {}
    body = entry.descriptor.environment
    return {
        "id": entry.snapshot.id,
        "version": entry.snapshot.version,
        "digest": entry.snapshot.digest,
        "sandbox": body.sandbox.value,
        "image": body.image,
        "python": body.python,
        "os": body.os,
        "network": body.network,
    }


def _plan_slots(
    plan: ExperimentPlan, tasks_by_id: dict[str, object], policy: object
) -> list[dict[str, object]]:
    """The matrix expanded into ordered slots, with the policy checked once.

    A slot is everything one run needs except the things that only exist while
    the run is in flight: the task as loaded from the dataset, the variant,
    the repetition and its position in the plan. The order is the plan's order
    — a reader of the results must not have to reconstruct it.
    """
    slots: list[dict[str, object]] = []
    for task in plan.tasks:
        loaded = tasks_by_id[task.uid]
        if policy.timeout_seconds is not None:
            task_timeout = loaded.task.task.timeout_seconds
            if task_timeout is not None and task_timeout > policy.timeout_seconds:
                raise ExperimentValidationError(
                    f"task {task.uid} declares timeout of {task_timeout}s, which exceeds "
                    f"the experiment execution policy timeout of {policy.timeout_seconds}s",
                    details={
                        "task_uid": task.uid,
                        "task_timeout_seconds": task_timeout,
                        "experiment_timeout_seconds": policy.timeout_seconds,
                    },
                )
        for variant in plan.variants:
            for repetition in range(plan.counts.repetitions):
                slots.append(
                    {
                        "index": len(slots) + 1,
                        "task": task,
                        "loaded": loaded,
                        "variant": variant,
                        "repetition": repetition,
                    }
                )
    return slots


def _slot_key(task_uid: str, variant_uid: str, repetition: int) -> tuple[str, str, int]:
    """The identity of one matrix cell, as the history records it.

    ``repetition`` is one-based here because that is how the history stores it:
    a resume asks the database which cells are done, and the answer has to be
    in the same vocabulary the database speaks.
    """
    return (task_uid, variant_uid, repetition)


def _run_experiment(
    context: CliContext,
    experiment: LoadedExperiment,
    plan: ExperimentPlan,
    *,
    store: bool,
    only: int | None = None,
    silent: bool = False,
    cancel_token: CancelToken | None = None,
    skip: set[tuple[str, str, int]] | None = None,
) -> dict[str, object]:
    """Execute the runs of a plan through the orchestrator.

    The runs share the descriptors and the dataset the plan pinned. When
    ``store`` is set, every run is also recorded in the history under the
    experiment's own identity and its variant, which is what makes the report
    and the export traceable back to the plan that produced them.

    With ``execution_policy.concurrency`` greater than one the runs go through
    a thread pool: an agent is a subprocess, so threads are the whole story
    (plan 15.2). The results come back in the plan's order, not the order in
    which the runs finished.
    """
    wall_start = time.monotonic()
    settings = context.loaded().settings
    paths = build_app_paths(settings)

    agents = _agent_registry(context)
    runtimes = _runtime_registry(context)
    workspaces = WorkspaceManager(
        RepositoryManager(paths.repositories_dir), paths.workspaces_dir
    )
    orchestrator = RunOrchestrator(
        agents=agents, runtimes=runtimes, workspaces=workspaces, evaluators=default_registry()
    )

    dataset = Dataset.load(paths.datasets_dir, base_dir=paths.project_root)
    tasks_by_id = {task.uid: task for task in dataset.tasks}

    url = resolve_database_url(settings)
    upgrade(url)
    store_history = HistoryStore(create_db_engine(url))
    registry = load_registry(paths.descriptors_dir)
    if store:
        store_history.record_plan(
            experiment_uid=experiment.identity,
            title=experiment.descriptor.title,
            description=experiment.descriptor.description,
            experiment_type=experiment.descriptor.experiment.type.value,
            descriptor_id=experiment.descriptor.id,
            descriptor_version=experiment.descriptor.version,
            config_hash=experiment.digest,
            experiment_yaml=_experiment_yaml(experiment),
            variants=[
                {
                    "uid": variant.variant_id,
                    "index": variant.index,
                    "values": variant.values,
                    "agent_config": variant.agent_config,
                    "environment_requests": variant.environment_requests,
                    "runtime_env": dict(variant.runtime_env),
                    "applies": variant.applies,
                    "config_hash": variant.config_hash,
                    "is_baseline": variant.is_baseline,
                }
                for variant in plan.variants
            ],
            snapshots=[_snapshot_payload(entry) for entry in _pinned_descriptors(registry, plan)],
        )

    policy = experiment.descriptor.experiment.execution_policy
    environment = _environment_snapshot(experiment, registry)
    slots = _plan_slots(plan, tasks_by_id, policy)
    skipped = 0
    if skip:
        pending = [
            slot
            for slot in slots
            if _slot_key(
                str(slot["task"].uid), str(slot["variant"].variant_id), int(slot["repetition"]) + 1
            )
            not in skip
        ]
        skipped = len(slots) - len(pending)
        slots = pending
    if only is not None:
        slots = slots[:only]
    concurrency = min(policy.concurrency, len(slots)) if slots else 1
    token = cancel_token if cancel_token is not None else CancelToken()

    print_lock = threading.Lock()

    def execute_slot(slot: dict[str, object]) -> dict[str, object] | None:
        # A queued slot never starts once the experiment is cancelled: the
        # operator asked for the matrix to stop, not for the rest of it to be
        # recorded as cancelled one run at a time.
        if token.cancelled:
            return None
        return _execute_one(
            context=context,
            orchestrator=orchestrator,
            dataset=dataset,
            paths=paths,
            plan=plan,
            experiment=experiment,
            policy=policy,
            environment=environment,
            slot=slot,
            store=store,
            silent=silent,
            cancel_token=token,
            print_lock=print_lock,
        )

    results: list[dict[str, object] | None] = [None] * len(slots)
    if concurrency <= 1:
        for position, slot in enumerate(slots):
            if token.cancelled:
                break
            results[position] = execute_slot(slot)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(execute_slot, slot): position for position, slot in enumerate(slots)
            }
            for future, position in futures.items():
                results[position] = future.result()

    runs = [result for result in results if result is not None]
    payload: dict[str, object] = {
        "runs": runs,
        "completed": len(runs),
        "planned": plan.counts.runs,
        "wall_seconds": round(time.monotonic() - wall_start, 1),
    }
    if token.cancelled:
        payload["cancelled"] = True
        payload["cancel_reason"] = token.reason
    if skipped:
        payload["already_done"] = skipped
    return payload


def _execute_one(
    *,
    context: CliContext,
    orchestrator: RunOrchestrator,
    dataset: Dataset,
    paths: object,
    plan: ExperimentPlan,
    experiment: LoadedExperiment,
    policy: object,
    environment: dict,
    slot: dict[str, object],
    store: bool,
    silent: bool,
    cancel_token: CancelToken,
    print_lock: threading.Lock,
) -> dict[str, object]:
    """One slot of the matrix: prepare, run, record, report.

    The run carries the experiment's cancel token. A token that never fires
    costs a check between phases and one watcher thread that asks the agent to
    stop when it does; the run then ends ``cancelled`` with its artifacts kept
    and its record saying why.
    """
    index = int(slot["index"])
    task = slot["task"]
    loaded = slot["loaded"]
    variant = slot["variant"]
    repetition = int(slot["repetition"])

    token = cancel_token

    task_desc = loaded.task
    task_title = task_desc.title or task.uid
    task_details = f"[bold cyan]{task.uid}[/bold cyan] ({task.category}, {task.difficulty})"
    variant_summary = variant.variant_id
    if variant.values:
        values_str = ", ".join(f"{k}={v}" for k, v in variant.values.items())
        variant_summary = f"{variant.variant_id} [{values_str}]"

    rep_info = f"rep {repetition + 1}/{plan.counts.repetitions}"
    if not silent:
        with print_lock:
            console.print(
                f"\n[dim][{index}/{plan.counts.runs}][/dim] Running task: {task_details}"
            )
            if task_desc.title:
                console.print(f"  [dim]title:[/dim]       {task_title}")
            console.print(f"  [dim]variant:[/dim]     {variant_summary}")
            console.print(
                f"  [dim]agent:[/dim]       {variant.agent_id} ({plan.mode}"
                f"{', runtime ' + plan.runtime_id if plan.runtime_id else ''})"
            )
            if variant.agent_config:
                console.print(f"  [dim]agent config:[/dim]{variant.agent_config}")
            if variant.runtime_env:
                declared = ", ".join(
                    f"{name}={value}"
                    for name, value in sorted(variant.runtime_env.items())
                )
                console.print(f"  [dim]runtime env:[/dim]  {declared}")
            console.print(f"  [dim]progress:[/dim]     {rep_info}")

    # Only the agent's own declared parameters go here: the mode and the
    # runtime are the orchestrator's, not agent configuration.
    agent_parameters = dict(variant.agent_config)
    artifacts_dir = paths.artifacts_dir / "runs" / _run_slug(  # type: ignore[union-attr]
        plan.agent_id, task.uid, variant.variant_id, repetition
    )
    # The clock starts here, before the run: the wait it counts
    # includes launching a managed instance, which is the part with
    # no other output to watch.
    clock = StepClock(f"[{index}/{plan.counts.runs}]")
    started_at = datetime.now(UTC)
    # A memory run's checkout has to declare the repository its
    # knowledge belongs to; the pin is empty for every other
    # experiment type, which leaves their run names as they were.
    pinned_workspace = _knowledge_workspace_id(
        experiment,
        agent_id=variant.agent_id,
        task_uid=task.uid,
        variant_id=variant.variant_id,
        repetition=repetition,
        repository_source=loaded.task.task.repository.source,
    )
    config = OrchestrationConfig(
        task=dataset.materialize(loaded),
        agent_id=variant.agent_id,
        agent_version=None,
        mode=plan.mode,
        runtime_id=plan.runtime_id,
        agent_parameters=agent_parameters,
        workspace_id=pinned_workspace,
        environment=environment or None,
        # Plugin factors are the runtime's own configuration: a
        # managed instance applies them as process environment, so
        # the variant value becomes the state of a process this run
        # started instead of a hope aimed at a shared router.
        runtime_environment=dict(variant.environment_requests),
        # The experiment's own declared launch environment comes first and the
        # variant's on top of it: the experiment says what every arm's instance
        # loads, the variant says what this arm says about itself, and an arm
        # that contradicts the experiment wins because it is the more specific
        # statement of the process about to start.
        runtime_env={**plan.runtime_env, **variant.runtime_env},
        artifacts_dir=artifacts_dir,
        evaluation_dir=artifacts_dir / "evaluation",
        agent_timeout=policy.timeout_seconds,
        evaluation_timeout=policy.evaluation_timeout_seconds,
        infrastructure_retries=policy.retry_infrastructure_errors,
        apply_mutation=True,
        cleanup_workspace=False,
        task_text=None,
        on_transition=clock.report_phase,
        cancel_token=token,
    )
    with clock.running(console, enabled=not silent):
        outcome = orchestrator.run(config)
    record = outcome.record or {}
    write_record(artifacts_dir / "run_record.json", record)
    if store:
        store_run(
            context,
            record,
            loaded=loaded,
            artifacts_dir=artifacts_dir,
            experiment_uid=experiment.identity,
            agent_id=variant.agent_id,
            agent_parameters=agent_parameters,
            variant_uid=variant.variant_id,
            repetition=repetition + 1,
        )

    state_color = STATE_COLORS.get(outcome.state.value, "white")
    score = (record.get("evaluation") or {}).get("score")
    score_str = f" score: {score:.2f}" if score is not None else ""
    detail = outcome.detail or record.get("error_message")
    if not silent:
        with print_lock:
            console.print(
                f"  [dim]outcome:[/dim]      "
                f"[{state_color}]{outcome.state.value}[/{state_color}]{score_str}"
            )
            # A state alone does not say why, and a run that ends
            # before the agent starts has no other output to read: the
            # reason is printed here rather than left in the record.
            if detail and outcome.state is not RunState.COMPLETED:
                for line in str(detail).splitlines():
                    console.print(f"  [dim]detail:[/dim]       {line}")
            console.print(
                f"  [dim]time:[/dim]         started {format_clock(started_at)}, took "
                f"[bold]{format_duration(clock.elapsed)}[/bold]"
            )
            # Where the time went is the run's own account, read back from
            # its transition log: a run that took four minutes and two of
            # them were the router starting is not a slow agent.
            phases = phase_durations(record)
            if len(phases) > 1:
                console.print(f"  [dim]phases:[/dim]       {format_phases(phases)}")

    return {
        "task_uid": task.uid,
        "variant": variant.variant_id,
        "repetition": repetition + 1,
        "state": outcome.state.value,
        "detail": detail,
        "run_uid": record.get("run_uid"),
        "score": score,
        "started_at": started_at.isoformat(),
        "elapsed_seconds": round(clock.elapsed, 1),
    }


def _run_slug(agent_id: str, task_uid: str, variant_uid: str, repetition: int) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    short = hashlib.sha256(f"{task_uid}/{variant_uid}/{repetition}".encode()).hexdigest()[:6]
    return f"{agent_id}-{stamp}-{short}"


@experiment_app.command("run")
@handle_errors
def experiment_run_cmd(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="Experiment file to run."),
    store_runs: bool = typer.Option(
        False, "--store", help="Record every run in the history (with its manifest).",
    ),
    only: int | None = typer.Option(
        None, "--only", help="Run at most this many runs of the matrix (for smoke tests).",
    ),
    concurrency: int | None = typer.Option(
        None,
        "--concurrency",
        help="Run this many runs at once; overrides execution_policy.concurrency.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run the experiment's matrix, concurrently when the policy says so."""
    context: CliContext = ctx.obj
    planner = _planner(context)
    experiment = load_experiment_file(Path(path))
    if concurrency is not None:
        experiment = _with_concurrency(experiment, concurrency)

    try:
        plan = planner.plan(experiment)
    except ExperimentValidationError as exc:
        console.print(f"[red]experiment is not runnable[/red] {exc}")
        for issue in exc.details.get("issues", []):
            console.print(f"  [red]error[/red] {issue['message']}")
        raise typer.Exit(1) from exc

    counts = plan.counts
    effective = experiment.descriptor.experiment.execution_policy.concurrency
    if not as_json:
        console.print(
            f"[cyan]running[/] {experiment.identity}: {counts.tasks} tasks x "
            f"{counts.variants} variants x {counts.repetitions} repetitions = "
            f"[bold]{counts.runs} runs[/bold]"
            + (f" [dim]concurrency {effective}[/dim]" if effective > 1 else "")
            + "\n"
        )

    result = _execute_matrix(
        context, experiment, plan, store=store_runs, only=only, silent=as_json
    )

    if as_json:
        show_json({"experiment": experiment.identity, **result})
        return

    states: dict[str, int] = {}
    for run in result["runs"]:
        states[str(run["state"])] = states.get(str(run["state"]), 0) + 1
    summary = ", ".join(f"{count} {state}" for state, count in sorted(states.items()))
    wall_seconds = result.get("wall_seconds")
    mean = wall_seconds / len(result["runs"]) if wall_seconds and result["runs"] else None
    spent = f" in {format_duration(wall_seconds)}" if wall_seconds else ""
    average = f" (mean {format_duration(mean)} per run)" if mean else ""
    console.print(
        f"  [green]done[/green] {result['completed']}/{result['planned']} runs{spent}: "
        f"{summary}{average}"
    )
    if store_runs:
        console.print("  [dim]recorded in the history; `akbench report all` renders it[/dim]")
    if result.get("cancelled"):
        console.print(f"  [yellow]cancelled[/yellow] {result.get('cancel_reason') or ''}")
        console.print(
            "  [dim]`akbench experiment resume "
            f"{result.get('experiment') or '<uid>'}` runs what is left[/dim]"
        )


def _with_concurrency(experiment: LoadedExperiment, concurrency: int) -> LoadedExperiment:
    """The same experiment with its concurrency overridden on the command line.

    A CLI override is not a new descriptor: it is the parsed one with one
    number changed, so every other validation of the plan still applies. The
    descriptor is frozen, hence the copy of its body's policy.
    """
    import copy

    clone = copy.deepcopy(experiment)
    policy = clone.descriptor.experiment.execution_policy
    policy.concurrency = concurrency
    return clone


def _execute_matrix(
    context: CliContext,
    experiment: LoadedExperiment,
    plan: ExperimentPlan,
    *,
    store: bool,
    only: int | None = None,
    silent: bool = False,
    skip: set[tuple[str, str, int]] | None = None,
) -> dict[str, object]:
    """Run a plan with cancellation wired up: Ctrl+C and ``experiment cancel``.

    The token is the one decision both cancel paths share: ``SIGINT`` fires it
    in this process, ``experiment cancel <uid>`` fires it through a marker file
    this process polls. The first Ctrl+C stops the matrix — the agent in flight
    is interrupted and recorded ``cancelled``, nothing new is started; the
    second one leaves the way it always did.
    """
    paths = build_app_paths(context.loaded().settings)
    token = CancelToken()
    marker = cancel_marker_path(paths.data_dir, experiment.identity)
    marker.parent.mkdir(parents=True, exist_ok=True)
    # A marker left by a cancel that arrived after the matrix was already done
    # must not cancel the next run of the same experiment before it starts.
    marker.unlink(missing_ok=True)
    source = FileCancelSource(marker)
    install_cancellation_handlers(token)
    source.watch(on_cancel=lambda: token.cancel(source.reason))
    try:
        result = _run_experiment(
            context,
            experiment,
            plan,
            store=store,
            only=only,
            silent=silent,
            cancel_token=token,
            skip=skip,
        )
    finally:
        source.stop()
        marker.unlink(missing_ok=True)
    result["experiment"] = experiment.identity
    return result


@experiment_app.command("resume")
@handle_errors
def experiment_resume_cmd(
    ctx: typer.Context,
    uid: str = typer.Argument(..., help="Experiment uid to resume (from the history)."),
    concurrency: int | None = typer.Option(
        None, "--concurrency", help="Override the experiment's concurrency for this resume."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run the matrix cells of a stored experiment that never reached a verdict.

    The plan is read back from the experiment file recorded with it, so a
    resume runs the plan that was run, not whatever the configuration directory
    says today. A cell is done when the history has a run of it in a terminal
    state — every terminal state except ``cancelled``, which is an operator
    asking, not a result: interrupted cells are exactly what a resume re-runs.
    A second resume of a finished experiment therefore does nothing, twice.
    """
    context: CliContext = ctx.obj
    settings = context.loaded().settings
    url = resolve_database_url(settings)
    store = HistoryStore(create_db_engine(url))

    experiment_row = next(
        (row for row in store.experiments() if row["uid"] == uid), None
    )
    if experiment_row is None:
        console.print(f"[red]unknown experiment[/red] {uid}")
        raise typer.Exit(1)
    if not experiment_row.get("experiment_yaml"):
        console.print(
            f"[red]experiment {uid} was recorded without its file[/red] "
            "there is no plan to resume; run it from its YAML again"
        )
        raise typer.Exit(1)

    done: set[tuple[str, str, int]] = set()
    rerun_cancelled = 0
    for run in store.runs(uid):
        key = _slot_key(
            str(run.get("task_uid")), str(run.get("variant_uid")), int(run.get("repetition") or 1)
        )
        status = run.get("status")
        if status == RunState.CANCELLED.value:
            rerun_cancelled += 1
            continue
        if status in {state.value for state in TERMINAL_STATES}:
            done.add(key)

    with tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", encoding="utf-8", delete=False
    ) as handle:
        handle.write(experiment_row["experiment_yaml"])
        path = Path(handle.name)
    try:
        experiment = load_experiment_file(path)
        if concurrency is not None:
            experiment = _with_concurrency(experiment, concurrency)
        plan = _planner(context).plan(experiment)
        if not as_json:
            counts = plan.counts
            console.print(
                f"[cyan]resuming[/] {uid}: {counts.runs} planned, "
                f"{len(done)} already decided"
                + (f", {rerun_cancelled} cancelled re-run" if rerun_cancelled else "")
                + "\n"
            )
        result = _execute_matrix(
            context, experiment, plan, store=True, skip=done, silent=as_json
        )
    finally:
        path.unlink(missing_ok=True)

    if as_json:
        show_json({"experiment": uid, "resumed": True, **result})
        return
    states: dict[str, int] = {}
    for run in result["runs"]:
        states[str(run["state"])] = states.get(str(run["state"]), 0) + 1
    summary = ", ".join(f"{count} {state}" for state, count in sorted(states.items())) or "nothing"
    console.print(
        f"  [green]done[/green] {result['completed']}/{result['planned']} runs: {summary}"
    )


@experiment_app.command("cancel")
@handle_errors
def experiment_cancel_cmd(
    ctx: typer.Context,
    uid: str = typer.Argument(..., help="Experiment uid to cancel."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Ask a running ``experiment run``/``resume`` of this uid to stop.

    There is no daemon to signal — the CLI is one-shot — so the request is a
    marker file the running process watches, and it takes effect within a
    second: the agent in flight is interrupted and recorded ``cancelled``, the
    rest of the matrix is not started. Artifacts of what already ran stay.
    When no experiment is running the marker is consumed by the next run of
    this uid starting (it clears it before the first run), which is why this
    command says what it did rather than promising more.
    """
    context: CliContext = ctx.obj
    paths = build_app_paths(context.loaded().settings)
    marker = cancel_marker_path(paths.data_dir, uid)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"cancelled at {datetime.now(UTC).isoformat()}\n", encoding="utf-8")
    if as_json:
        show_json({"experiment": uid, "cancelled": True, "marker": str(marker)})
        return
    console.print(f"[yellow]cancellation requested[/yellow] for {uid}")
    console.print(
        "  [dim]a running `akbench experiment run`/`resume` of this uid stops "
        "within a second; a run that starts later clears the request[/dim]"
    )


@experiment_app.command("show")
@handle_errors
def experiment_show_cmd(
    ctx: typer.Context,
    uid: str = typer.Argument(..., help="Experiment uid (from the history)."),
    as_json: bool = JSON_OPTION,
) -> None:
    """One recorded experiment: its plan, its variants, its runs, its metrics.

    Everything is read from the history, including the experiment file as it
    was run: a page that explains itself months later, with no checkout of the
    configuration directory and no trust in what the descriptors claim today.
    """
    context: CliContext = ctx.obj
    settings = context.loaded().settings
    store = HistoryStore(create_db_engine(resolve_database_url(settings)))

    row = next((item for item in store.experiments() if item["uid"] == uid), None)
    if row is None:
        console.print(f"[red]unknown experiment[/red] {uid}")
        raise typer.Exit(1)
    variants = store.variants(uid)
    runs = store.runs(uid)
    metrics = store.metrics(uid)

    if as_json:
        show_json(
            {**row, "variants": variants, "runs": runs, "metrics": metrics}
        )
        return

    console.print(f"[bold]{row['uid']}[/]  {row['title'] or ''}")
    if row.get("description"):
        console.print(f"  [dim]{row['description']}[/dim]")
    console.print(f"  type       {row.get('type') or '—'}")
    if row.get("descriptor"):
        console.print(f"  descriptor {row['descriptor']}")
    if row.get("validity"):
        console.print(f"  validity   {row['validity']}")
    if row.get("config_hash"):
        console.print(f"  digest     {row['config_hash']}")

    if variants:
        console.print(f"\n  [bold]{len(variants)} variant(s)[/bold]")
        for variant in variants:
            values = variant.get("values") or {}
            rendered = ", ".join(f"{k}={v}" for k, v in values.items()) or "—"
            baseline = " [bold]baseline[/bold]" if variant.get("is_baseline") else ""
            console.print(f"    {variant.get('uid')}  {rendered}{baseline}")

    if runs:
        console.print(f"\n  [bold]{len(runs)} run(s)[/bold]")
        for run in runs:
            status = run.get("status") or "—"
            evaluation = run.get("evaluation") or {}
            score = evaluation.get("score")
            score_str = f" score {score:.2f}" if isinstance(score, int | float) else ""
            verdict = evaluation.get("verdict")
            verdict_str = f" {verdict}" if verdict else ""
            color = STATE_COLORS.get(str(status), "white")
            console.print(
                f"    {run.get('uid')}  {run.get('task_uid')} "
                f"{run.get('variant_uid')} rep{run.get('repetition')} "
                f"[{color}]{status}[/{color}]{verdict_str}{score_str}"
            )
    if metrics:
        console.print(f"\n  [bold]{len(metrics)} metric(s)[/bold]")
        for metric in metrics:
            value = metric.get("value")
            rendered = (
                f"{value:.4f}".rstrip("0").rstrip(".") if isinstance(value, int | float) else "—"
            )
            availability = metric.get("availability") or metric.get("status") or ""
            console.print(
                f"    {metric.get('metric_id')}  {rendered}  [dim]{availability}[/dim]"
            )
    if not runs:
        console.print("\n  [dim]no runs recorded yet[/dim]")


def _experiment_yaml(experiment: LoadedExperiment) -> str | None:
    """The experiment file as written, so the plan can be read from history.

    The plan is derived and the digest pins it; the file is what the operator
    actually asked for. Recording it means an experiment page explains itself
    months later, with no checkout of the configuration directory.
    """
    path = getattr(experiment, "path", None)
    if path is None:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


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
    registry: DescriptorRegistry, plan: ExperimentPlan
) -> list[LoadedDescriptor]:
    """Resolve the descriptors a plan pinned, keeping the exact versions it used."""
    entries: list[LoadedDescriptor] = []
    wanted: list[tuple[DescriptorKind, str]] = [(DescriptorKind.AGENT, plan.agent_id)]
    if plan.runtime_id:
        wanted.append((DescriptorKind.RUNTIME, plan.runtime_id))
    for kind, identity in wanted:
        entry = registry.get(kind, identity)
        if entry is not None:
            entries.append(entry)
    for pinned in plan.descriptor_snapshots:
        kind_part, _, rest = pinned.partition(":")
        try:
            kind = DescriptorKind(kind_part)
        except ValueError:
            continue
        entry = registry.get(kind, rest)
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
    registry = load_registry(build_app_paths(settings).descriptors_dir)

    experiment = plan.experiment
    body = experiment.descriptor.experiment
    stored = store.record_plan(
        experiment_uid=experiment.identity,
        title=experiment.descriptor.title,
        description=experiment.descriptor.description,
        experiment_type=body.type.value,
        descriptor_id=experiment.descriptor.id,
        descriptor_version=experiment.descriptor.version,
        config_hash=experiment.digest,
        experiment_yaml=_experiment_yaml(experiment),
        variants=[
            {
                "uid": variant.variant_id,
                "index": variant.index,
                "values": variant.values,
                "agent_config": variant.agent_config,
                "environment_requests": variant.environment_requests,
                "runtime_env": dict(variant.runtime_env),
                "applies": variant.applies,
                "config_hash": variant.config_hash,
                "is_baseline": variant.is_baseline,
            }
            for variant in plan.variants
        ],
        snapshots=[_snapshot_payload(entry) for entry in _pinned_descriptors(registry, plan)],
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

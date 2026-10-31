"""``akbench knowledge``: plan and inspect memory experiments.

A memory experiment is a comparison, and a comparison is only as good as the
things it held equal. The commands here build the plan — the learning arm, the
replay and the fresh control — show the fingerprints that prove which arms
differ in knowledge and in nothing else, and show the readiness gate a replay
must pass. Nothing is run; the plan is what a reader checks before agents
start spending tokens.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths
from akbench.datasets import Dataset, TaskLoadError
from akbench.descriptors import DescriptorKind, PluginDescriptor, load_registry
from akbench.experiments import (
    LoadedExperiment,
    load_experiment_directory,
    load_experiment_file,
)
from akbench.experiments.descriptor import ExperimentType
from akbench.knowledge.planning import MemoryExperimentPlan, MemoryPlanBuilder
from akbench.knowledge.readiness import NoReadbackProbe

knowledge_app = typer.Typer(
    help="Plan and inspect knowledge replay experiments.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")
DEFAULT_EXPERIMENT_DIR = "configs/experiments"


def _plugin(context: CliContext) -> PluginDescriptor | None:
    paths = build_app_paths(context.loaded().settings)
    registry = load_registry(paths.descriptors_dir)
    for entry in registry.entries(DescriptorKind.PLUGIN):
        descriptor = entry.descriptor
        if isinstance(descriptor, PluginDescriptor) and descriptor.plugin.type == "knowledge":
            return entry.descriptor
    return None


def _builder(context: CliContext, lifecycle: str | None) -> MemoryPlanBuilder:
    paths = build_app_paths(context.loaded().settings)
    try:
        dataset = Dataset.load(paths.datasets_dir, base_dir=paths.project_root)
    except TaskLoadError as exc:
        console.print(f"[red]dataset is not usable[/red] {exc}")
        raise typer.Exit(1) from exc
    plugin = _plugin(context)
    return MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle=lifecycle)


def _default_experiment_dir(context: CliContext) -> Path:
    """The project's experiment directory, not whatever CWD says."""
    paths = build_app_paths(context.loaded().settings)
    return paths.project_root / DEFAULT_EXPERIMENT_DIR


def _load_memory_experiments(
    context: CliContext, paths: list[str]
) -> list[LoadedExperiment]:
    """Load the given files, or the project's experiment directory, keeping memory ones."""
    targets = [Path(item) for item in paths] if paths else [_default_experiment_dir(context)]
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
    memory = [
        item
        for item in loaded
        if item.descriptor.experiment.type is ExperimentType.KNOWLEDGE_REPLAY
    ]
    if not memory:
        console.print(
            f"[red]no knowledge_replay experiment found[/red] among the {len(loaded)} loaded; "
            f"expected under {DEFAULT_EXPERIMENT_DIR}"
        )
        raise typer.Exit(1)
    return memory


def _lifecycle_of(experiment: LoadedExperiment) -> str | None:
    runtime = experiment.descriptor.experiment.execution.runtime
    return runtime.lifecycle if runtime is not None else None


def _print_plan(plan: MemoryExperimentPlan) -> None:
    console.print(
        f"[bold]{plan.experiment_uid}[/bold] · plugin "
        f"{plan.plugin_id}@{plan.plugin_version}"
    )
    console.print(
        f"  learning session  [cyan]{plan.learning_session.session_id}[/] "
        f"digest {plan.learning_session.digest[7:19]}"
    )
    for arm in plan.learning:
        access = _access_label(arm.knowledge_access)
        console.print(
            f"  [green]learning[/]  {arm.task_uid}  knowledge={access} "
            f"fp={arm.fingerprint.digest[7:19]}"
        )

    for scenario in plan.scenarios:
        console.print(f"\n  scenario [bold]{scenario.id}[/] ({scenario.type.value})")
        for arm in (arm for arm in plan.arms if arm.arm_id.endswith(f"-{scenario.id}")):
            label = {"replay": "replay", "fresh": "fresh"}[arm.mode.value]
            color = {"replay": "cyan", "fresh": "dim"}[arm.mode.value]
            gate = ""
            if arm.gate is not None:
                gate = (
                    f" gate=[{'green' if arm.gate.allowed else 'red'}]"
                    f"{'allowed' if arm.gate.allowed else 'blocked'}[/]"
                )
            console.print(
                f"    [{color}]{label:<6}[/] {arm.task_uid} "
                f"knowledge={_access_label(arm.knowledge_access)} "
                f"fp={arm.fingerprint.digest[7:19]}{gate}"
            )
            if arm.gate is not None and arm.gate.reason:
                console.print(f"          [dim]{arm.gate.reason}[/dim]")

    console.print(
        f"\n  isolation       namespace={plan.isolation.namespace_isolated.value} "
        f"comparable={plan.isolation.comparable}"
    )
    if plan.isolation.namespace_reason:
        console.print(f"  [dim]{plan.isolation.namespace_reason}[/dim]")

    for issue in plan.validation.issues:
        color = "red" if issue.severity.value == "error" else "yellow"
        console.print(f"  [{color}]{issue.severity.value}[/{color}] {issue.message}")


def _access_label(access: dict[str, bool]) -> str:
    return "on" if access.get("read") and access.get("write") else (
        "read" if access.get("read") else "off"
    )


@knowledge_app.command("plan")
@handle_errors
def knowledge_plan_cmd(
    ctx: typer.Context,
    paths: list[str] = typer.Argument(None, help="Experiment files or directories."),
    allow_unverified: bool = typer.Option(
        False,
        "--allow-unverified",
        help="Build the plan with the replay gate allowed to pass unverified.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Build the memory plan: arms, fingerprints, readiness gate, isolation."""
    context: CliContext = ctx.obj

    loaded = _load_memory_experiments(context, paths)
    plans = []
    for item in loaded:
        builder = _builder(context, _lifecycle_of(item))
        plans.append(builder.plan(item, allow_unverified=allow_unverified))

    if as_json:
        show_json([plan.as_dict() for plan in plans])
        return

    for plan in plans:
        _print_plan(plan)
    raise typer.Exit(0)


@knowledge_app.command("readiness")
@handle_errors
def knowledge_readiness_cmd(
    ctx: typer.Context,
    session_file: Path = typer.Option(
        None,
        "--session",
        help="A learning-session manifest (JSON) to check a replay gate against.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show what this deployment can say about a knowledge base before a replay.

    Without a session file the answer is about the deployment itself: what
    readiness means here and what the default probe reports.
    """
    context: CliContext = ctx.obj
    plugin = _plugin(context)
    lifecycle = "managed" if _builder(context, "managed").lifecycle else "external"

    probe = NoReadbackProbe()
    from akbench.knowledge.sessions import LearningSession

    if session_file is not None:
        try:
            payload = json.loads(session_file.read_text(encoding="utf-8"))
            session = LearningSession.from_dict(payload)
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            console.print(f"[red]cannot read learning session[/red] {session_file}: {exc}")
            raise typer.Exit(1) from exc
    else:
        session = LearningSession(
            session_id="<no session>",
            experiment_uid="<unknown>",
            plugin_id=plugin.id if plugin else "agentic_knowledge",
            plugin_version=plugin.version if plugin else "",
        )

    from akbench.knowledge.readiness import build_readiness_gate

    gate = build_readiness_gate(session, probe)
    readiness = gate.readiness

    if as_json:
        show_json(
            {
                "deployment": {"plugin": plugin.id if plugin else None, "lifecycle": lifecycle},
                "session": session.as_dict(),
                "readiness": readiness.as_dict(),
                "gate": gate.as_dict(),
            }
        )
        return

    console.print(f"[bold]knowledge base readiness[/bold] · {lifecycle} instance")
    console.print(f"  status   [{'green' if readiness.confirmed else 'yellow'}]"
                  f"{readiness.status.value}[/]")
    console.print(f"  writes   {readiness.writes_settled}")
    console.print(f"  indexing {readiness.indexing_settled}")
    if readiness.note:
        console.print(f"  [dim]{readiness.note}[/dim]")
    console.print(f"  gate     {'allowed' if gate.allowed else 'blocked'} ({gate.reason})")

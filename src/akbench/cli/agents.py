"""Agent run commands: execute one agent task through the universal contract.

This module is the runner's view of agents and contains no knowledge of any
concrete agent. It resolves the agent from the descriptor registry, instantiates
its adapter through the catalog, validates the configuration against the
descriptor, and drives the run through the :class:`AgentAdapter` contract only.
Adding a new agent therefore never changes this code.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import typer

from akbench.agents.catalog import binding_from_runtime, build_agent_registry
from akbench.agents.contract import AgentConfig
from akbench.agents.registry import AgentEntry, validate_agent_config
from akbench.cli.common import CliContext, console, handle_errors, show_json

# ``agent list``/``agent inspect`` live with the descriptor commands; the run
# command extends the same group so the CLI keeps one ``agent`` namespace.
from akbench.cli.descriptors import agent_app
from akbench.config.loader import build_app_paths
from akbench.datasets import Dataset, RepositoryManager, TaskLoadError, WorkspaceManager
from akbench.descriptors import (
    AgentDescriptor,
    DescriptorKind,
    RuntimeDescriptor,
    load_registry,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")


def _descriptor_registry(context: CliContext):
    paths = build_app_paths(context.loaded().settings)
    try:
        return load_registry(paths.descriptors_dir)
    except Exception as exc:
        console.print(f"[red]descriptor registry not usable[/red] {exc}")
        raise typer.Exit(1) from exc


def _agent_entry(context: CliContext, reference: str) -> AgentEntry:
    registry = _descriptor_registry(context)
    agent_descriptors = [
        entry.descriptor
        for entry in registry.entries(DescriptorKind.AGENT)
        if isinstance(entry.descriptor, AgentDescriptor)
    ]
    try:
        agent_registry = build_agent_registry(
            agent_descriptors, allow_missing_adapter=True
        )
    except Exception as exc:
        console.print(f"[red]agent registry not usable[/red] {exc}")
        raise typer.Exit(1) from exc

    try:
        agent_id, version = _split_reference(reference)
    except ValueError as exc:
        console.print(f"[red]invalid agent reference[/red] {exc}")
        raise typer.Exit(1) from exc
    try:
        entry = agent_registry.resolve(agent_id, version)
    except Exception as exc:
        console.print(f"[red]cannot resolve agent[/red] {exc}")
        raise typer.Exit(1) from exc
    return entry


def _split_reference(reference: str) -> tuple[str, str | None]:
    if "@" in reference:
        agent_id, version = reference.split("@", 1)
        return agent_id, version or None
    return reference, None


def _runtime_binding(context: CliContext, runtime: str | None):
    if runtime is None:
        return None
    registry = _descriptor_registry(context)
    loaded = registry.get(DescriptorKind.RUNTIME, runtime)
    if loaded is None or not isinstance(loaded.descriptor, RuntimeDescriptor):
        console.print(f"[red]runtime {runtime!r} is not registered[/red]")
        raise typer.Exit(1)
    return binding_from_runtime(loaded.descriptor)  # type: ignore[arg-type]


def _prepared_workspace(
    context: CliContext, task: str
) -> tuple[Path, dict[str, object], object]:
    """Prepare the workspace of a dataset task, returning the loaded task too."""
    paths = build_app_paths(context.loaded().settings)
    try:
        dataset = Dataset.load(paths.datasets_dir, base_dir=paths.project_root)
        loaded = dataset.require(task)
    except TaskLoadError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    repos = RepositoryManager(paths.repositories_dir)
    workspaces = WorkspaceManager(repos, paths.workspaces_dir)
    materialized = dataset.materialize(loaded)
    workspace_id = "agent-" + hashlib.sha256(
        f"{loaded.uid}:{time.time()}".encode()
    ).hexdigest()[:10]
    try:
        prepared = workspaces.prepare(materialized.task, workspace_id, task_dir=loaded.path)
    except Exception as exc:
        console.print(f"[red]workspace preparation failed[/red] {exc}")
        raise typer.Exit(1) from exc
    return prepared.path, prepared.as_dict(), loaded


def _parse_parameters(values: list[str]) -> dict[str, object]:
    """Parse ``name=value`` pairs; the descriptor decides what is acceptable.

    Values are parsed as YAML so booleans and numbers keep their type, exactly
    like configuration overrides elsewhere in the CLI.
    """
    import yaml

    parsed: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            console.print(f"[red]--param expects name=value[/red] got {value!r}")
            raise typer.Exit(1)
        name, _, raw = value.partition("=")
        name = name.strip()
        try:
            parsed[name] = yaml.safe_load(raw)
        except yaml.YAMLError:
            parsed[name] = raw
    return parsed


def _task_text(path: Path) -> str:
    if not path.is_file():
        console.print(f"[red]task file not found[/red] {path}")
        raise typer.Exit(1)
    return path.read_text(encoding="utf-8").strip()


def _task_prompt(task_file: Path | None, task: str | None, loaded: object | None) -> str:
    """The text handed to the agent: a file wins, otherwise the task description.

    A task carries its prompt in ``description.md`` next to ``task.yaml``; only
    the task itself can supply it, and the CLI never invents one.
    """
    if task_file is not None:
        return _task_text(task_file)
    if loaded is None:
        console.print("[red]provide --task-file or --task[/red]")
        raise typer.Exit(1)
    from akbench.datasets.dataset import DESCRIPTION_FILE

    directory = Path(loaded.path)  # type: ignore[attr-defined]
    description = directory / DESCRIPTION_FILE
    if description.is_file():
        return description.read_text(encoding="utf-8").strip()
    declared = getattr(loaded.task, "description", None)  # type: ignore[attr-defined]
    if declared:
        return str(declared).strip()
    console.print(f"[red]task {task!r} declares no prompt text[/red]")
    raise typer.Exit(1)


@agent_app.command("run")
@handle_errors
def agent_run_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Agent id or id@version."),
    task_file: Path | None = typer.Option(
        None, "--task-file", "-t", help="File with the task text (plain text or YAML)."
    ),
    task: str | None = typer.Option(
        None, "--task", help="Task id or id@version to prepare a workspace for."
    ),
    workspace: Path | None = typer.Option(
        None, "--workspace", "-w", help="Use this existing workspace directory."
    ),
    runtime: str | None = typer.Option(
        None, "--runtime", help="Runtime id to bind (provides base_url and credential)."
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Wall-clock seconds before the run is cancelled."
    ),
    model: str | None = typer.Option(
        None, "--model", help="Model alias, when the agent accepts one."
    ),
    param: list[str] = typer.Option(
        [],
        "--param",
        help="Agent configuration as name=value (repeatable); each name must be "
        "declared controllable by the agent descriptor.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run one task through one agent, reporting the universal normalized result."""
    context: CliContext = ctx.obj

    entry = _agent_entry(context, reference)
    descriptor = entry.descriptor
    binding = _runtime_binding(context, runtime)

    parameters: dict[str, object] = {}
    if model is not None:
        parameters["model"] = model
    parameters.update(_parse_parameters(param))

    config = AgentConfig(
        agent_id=descriptor.id,
        parameters=parameters,
        runtime=binding,
    )

    # Validate against the descriptor before touching the filesystem.
    try:
        validate_agent_config(descriptor, config)
    except Exception as exc:
        console.print(f"[red]invalid agent configuration[/red] {exc}")
        raise typer.Exit(1) from exc

    loaded_task: object | None = None
    if workspace is not None:
        if not workspace.is_dir():
            console.print(f"[red]workspace is not a directory[/red] {workspace}")
            raise typer.Exit(1)
        workspace_path, provenance = workspace, None
    elif task is not None:
        workspace_path, provenance, loaded_task = _prepared_workspace(context, task)
    else:
        console.print("[red]provide --workspace or --task[/red]")
        raise typer.Exit(1)
    task_text = _task_prompt(task_file, task, loaded_task)

    # Rebuild config now that we know where artifacts live (one dir per run).
    paths = build_app_paths(context.loaded().settings)
    artifacts = paths.artifacts_dir / "agent-runs" / time.strftime("%Y%m%d-%H%M%S")
    config = AgentConfig(
        agent_id=descriptor.id,
        parameters=parameters,
        artifacts_dir=artifacts,
        runtime=binding,
    )

    adapter = entry.adapter()
    try:
        adapter.validate_environment(config)
    except Exception as exc:
        console.print(f"[red]environment check failed[/red] {exc}")
        raise typer.Exit(1) from exc

    session = adapter.start_session(config, workspace_path)
    adapter.submit_task(session, task_text)
    adapter.wait_for_completion(session, timeout=timeout)
    result = adapter.close_session(session)

    payload = result.as_dict()
    payload["workspace"] = str(workspace_path)
    payload["workspace_provenance"] = provenance
    payload["agent"] = reference

    if as_json:
        show_json(payload)
        return

    status = result.status.value
    color = "green" if status == "completed" else ("yellow" if status == "timeout" else "red")
    console.print(f"[{color}]agent run finished: {status}[/{color}]")
    console.print(f"  agent        {result.agent_id} {result.agent_version or ''}")
    console.print(f"  session      {result.session_id or '—'}")
    console.print(f"  exit_code    {result.exit_code if result.exit_code is not None else '—'}")
    console.print(f"  workspace    {workspace_path}")
    if result.final_message:
        console.print(f"  final        {result.final_message[:120]}")
    if result.usage and any(result.usage.as_dict().values()):
        usage = result.usage
        console.print(
            f"  tokens       in={usage.input_tokens} out={usage.output_tokens} "
            f"total={usage.total_tokens}"
        )
    if result.observations.get("tool_call_count"):
        console.print(f"  tool_calls   {result.observations['tool_call_count']}")
    if result.artifacts:
        console.print("  artifacts    " + ", ".join(sorted(result.artifacts)))

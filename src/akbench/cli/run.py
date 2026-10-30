"""``akbench run``: one orchestrated run of one agent on one task.

The command wires the generic contracts together — agent registry, runtime
registry, workspace manager and evaluator engine — and hands a single run to
the :class:`RunOrchestrator`. It never names a concrete agent: the same code
path serves any agent that has a descriptor and an adapter, and the verdict
comes from the task's own evaluator, not from the agent (plan sections 14, 15).

Every run writes a run record next to the agent's artifacts: the lifecycle
transition log, the workspace fingerprints, the agent observations and the
evaluation verdict. That record is the audit trail of one run and the input to
storage and reports in later phases.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from akbench.agents.catalog import build_agent_registry
from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths
from akbench.datasets import Dataset, RepositoryManager, TaskLoadError, WorkspaceManager
from akbench.descriptors import AgentDescriptor, DescriptorKind, RuntimeDescriptor, load_registry
from akbench.evaluators.registry import default_registry
from akbench.orchestration import OrchestrationConfig, RunOrchestrator, RunState
from akbench.runtime import build_runtime_registry

run_app = typer.Typer(
    help="Run one task through one agent and evaluate the result.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")

VERDICT_COLORS = {
    "passed": "green",
    "partial": "yellow",
    "failed": "red",
    "regression": "red",
    "timeout": "yellow",
    "evaluator_error": "magenta",
    "infrastructure_error": "magenta",
}

STATE_COLORS = {
    "completed": "green",
    "failed": "red",
    "timeout": "yellow",
    "cancelled": "yellow",
    "infrastructure_error": "magenta",
    "invalid_configuration": "magenta",
    "evaluation_error": "magenta",
}


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


def _parse_parameters(values: list[str]) -> dict[str, object]:
    """Parse ``name=value`` pairs as YAML, exactly as ``agent run`` does."""
    import yaml

    parsed: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            console.print(f"[red]--param expects name=value[/red] got {value!r}")
            raise typer.Exit(1)
        name, _, raw = value.partition("=")
        try:
            parsed[name.strip()] = yaml.safe_load(raw)
        except yaml.YAMLError:
            parsed[name.strip()] = raw
    return parsed


def _print_evaluation(evaluation: dict[str, object]) -> None:
    """One line per facet of the evaluation, skipping whatever is unknown."""
    verdict = evaluation.get("verdict")
    if verdict:
        console.print(f"  evaluation [{VERDICT_COLORS.get(str(verdict), 'white')}]{verdict}[/]")
    if evaluation.get("total") is not None:
        passed = evaluation.get("passed") or 0
        failed = evaluation.get("failed") or 0
        console.print(
            f"  tests      {passed} passed, {failed} failed of {evaluation['total']}"
        )
    if evaluation.get("score") is not None:
        console.print(f"  score      {float(evaluation['score']):.3f}")


def _write_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, indent=2, ensure_ascii=False, default=str)
    path.write_text(payload + "\n", encoding="utf-8")


@run_app.command("single")
@handle_errors
def run_single_cmd(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="Task id or id@version."),
    agent: str = typer.Option(..., "--agent", "-a", help="Agent id or id@version."),
    mode: str = typer.Option(
        "direct", "--mode", "-m", help="Execution mode: direct, runtime or router."
    ),
    runtime: str | None = typer.Option(None, "--runtime", "-r", help="Runtime id for the mode."),
    task_file: Path | None = typer.Option(
        None, "--task-file", "-t", help="Override the task prompt with this file."
    ),
    param: list[str] = typer.Option(
        [],
        "--param",
        help="Agent configuration as name=value (repeatable).",
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Wall-clock seconds before the agent run is cancelled."
    ),
    evaluation_timeout: float | None = typer.Option(
        None, "--evaluation-timeout", help="Wall-clock seconds for the evaluation step."
    ),
    infrastructure_retries: int = typer.Option(
        0,
        "--infrastructure-retries",
        help="Retry budget for infrastructure failures only; agent failures are never retried.",
    ),
    no_mutation: bool = typer.Option(
        False, "--no-mutation", help="Skip the task's mutation (run against the pristine repo)."
    ),
    cleanup: bool = typer.Option(
        False, "--cleanup", help="Remove the run's workspace when the run finishes."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Orchestrate one run: prepare, execute, evaluate, record."""
    context: CliContext = ctx.obj
    paths = build_app_paths(context.loaded().settings)

    try:
        dataset = Dataset.load(paths.datasets_dir, base_dir=paths.project_root)
        loaded = dataset.require(task)
    except TaskLoadError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    materialized = dataset.materialize(loaded)
    agent_registry = _agent_registry(context)
    agent_id, _, requested_version = agent.partition("@")
    agent_version = requested_version or None
    try:
        agent_registry.resolve(agent_id, agent_version)
    except Exception as exc:
        console.print(f"[red]cannot resolve agent[/red] {exc}")
        raise typer.Exit(1) from exc

    parameters = _parse_parameters(param)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    artifacts_dir = paths.artifacts_dir / "runs" / f"{agent_id}-{stamp}"
    evaluation_dir = artifacts_dir / "evaluation"
    task_text = task_file.read_text(encoding="utf-8").strip() if task_file else None

    config = OrchestrationConfig(
        task=materialized,
        agent_id=agent_id,
        agent_version=agent_version,
        mode=mode,
        runtime_id=runtime,
        agent_parameters=parameters,
        artifacts_dir=artifacts_dir,
        evaluation_dir=evaluation_dir,
        agent_timeout=timeout,
        evaluation_timeout=evaluation_timeout,
        infrastructure_retries=infrastructure_retries,
        apply_mutation=not no_mutation,
        cleanup_workspace=cleanup,
        task_text=task_text,
    )

    orchestrator = RunOrchestrator(
        agents=agent_registry,
        runtimes=_runtime_registry(context),
        workspaces=WorkspaceManager(
            RepositoryManager(paths.repositories_dir), paths.workspaces_dir
        ),
        evaluators=default_registry(),
    )
    outcome = orchestrator.run(config)
    record = outcome.record or {}
    _write_record(artifacts_dir / "run_record.json", record)

    payload = outcome.as_dict()
    payload["task"] = loaded.uid
    payload["agent"] = agent
    payload["mode"] = mode
    payload["runtime"] = runtime
    payload["workspace"] = record.get("workspace_path")
    evaluation = record.get("evaluation")
    if isinstance(evaluation, dict):
        # ``raw`` is the verbatim evaluator report and belongs in the artifact,
        # not in a stream a human or a script reads.
        payload["evaluation"] = {k: v for k, v in evaluation.items() if k != "raw"}
    else:
        payload["evaluation"] = None
    payload["record"] = str(artifacts_dir / "run_record.json")

    if as_json:
        show_json(payload)
    else:
        color = STATE_COLORS.get(outcome.state.value, "white")
        console.print(f"[{color}]run finished: {outcome.state.value}[/{color}]")
        if outcome.detail:
            console.print(f"  detail     {outcome.detail}")
        if record:
            console.print(f"  run        {outcome.run_uid}")
            console.print(f"  task       {loaded.uid}")
            console.print(f"  workspace  {record.get('workspace_path') or '—'}")
            evaluation = record.get("evaluation")
            if isinstance(evaluation, dict):
                _print_evaluation(evaluation)
        console.print(f"  record     {artifacts_dir / 'run_record.json'}")

    raise typer.Exit(0 if outcome.state is RunState.COMPLETED and outcome.ok else 1)

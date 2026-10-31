"""``akbench evaluate``: judge what an agent produced for a task.

The verdict comes from the task's own evaluator and hidden tests, run outside
the agent workspace, so an agent's claim about its own result is never part of
the measurement (plan sections 8.6 and 16).
"""

from __future__ import annotations

from pathlib import Path

import typer

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths
from akbench.datasets import Dataset, TaskLoadError
from akbench.evaluators.registry import default_registry
from akbench.evaluators.task_evaluation import evaluate_task

evaluate_app = typer.Typer(
    help="Evaluate a produced workspace against a task.",
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


@evaluate_app.command("task")
@handle_errors
def evaluate_task_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Task id or id@version."),
    workspace: Path = typer.Option(
        ..., "--workspace", "-w", help="Directory the agent worked in."
    ),
    out_dir: Path | None = typer.Option(
        None, "--out", help="Where to store raw evaluator reports."
    ),
    evaluator: str | None = typer.Option(
        None, "--evaluator", help="Override the evaluator declared by the task."
    ),
    timeout: float | None = typer.Option(None, "--timeout", help="Evaluator timeout in seconds."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run the task's evaluator over a workspace and report the verdict."""
    context: CliContext = ctx.obj
    paths = build_app_paths(context.loaded().settings)
    try:
        dataset = Dataset.load(paths.datasets_dir, base_dir=paths.project_root)
        loaded = dataset.require(reference)
    except TaskLoadError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if not workspace.is_dir():
        console.print(f"[red]workspace is not a directory[/red] {workspace}")
        raise typer.Exit(1)

    reports = out_dir or (paths.artifacts_dir / "evaluations" / loaded.uid)
    result = evaluate_task(
        loaded,
        workspace,
        reports,
        evaluator_id=evaluator,
        registry=default_registry(),
        timeout=timeout,
    )

    payload = result.as_dict()
    payload["task"] = loaded.uid
    payload["workspace"] = str(workspace)
    if as_json:
        show_json(payload)
    else:
        color = VERDICT_COLORS.get(result.verdict.value, "white")
        console.print(f"[{color}]verdict: {result.verdict.value}[/{color}] ({result.evaluator_id})")
        counts = "—", "—"
        if result.total is not None:
            counts = (
                f"{result.passed or 0} passed",
                f"{result.failed or 0} failed",
            )
            console.print(f"  tests      {counts[0]}, {counts[1]} of {result.total}")
        if result.score is not None:
            console.print(f"  score      {result.score:.3f}")
        duration = result.duration_seconds if result.duration_seconds is not None else "—"
        console.print(f"  duration   {duration}s")
        console.print(f"  artifacts  {', '.join(sorted(result.artifacts)) or '—'}")
        if result.details.get("reason"):
            console.print(f"  [dim]{result.details['reason']}[/dim]")

    # A measurement that broke is a tooling problem (exit 2); the agent simply
    # not solving the task is a normal outcome (exit 1), and a pass is 0.
    if result.verdict.value in {"evaluator_error", "infrastructure_error"}:
        raise typer.Exit(2)
    raise typer.Exit(0 if result.ok else 1)

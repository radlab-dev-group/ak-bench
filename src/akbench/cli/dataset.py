"""Dataset commands: list, validate and inspect tasks and their workspaces."""

from __future__ import annotations

import typer
from rich.table import Table

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths
from akbench.datasets import RepositoryManager, WorkspaceManager
from akbench.datasets.dataset import Dataset, TaskLoadError
from akbench.datasets.repository import is_seed_directory
from akbench.datasets.verification import MutationVerifier
from akbench.descriptors import load_registry

dataset_app = typer.Typer(help="List, validate and inspect benchmark tasks.", no_args_is_help=True)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")


def _dataset(context: CliContext) -> Dataset:
    paths = build_app_paths(context.loaded().settings)
    try:
        return Dataset.load(paths.datasets_dir, base_dir=paths.project_root)
    except TaskLoadError as exc:
        console.print(f"[red]dataset is not usable[/red] {exc}")
        raise typer.Exit(1) from exc


def _registry(context: CliContext):
    paths = build_app_paths(context.loaded().settings)
    try:
        return load_registry(paths.descriptors_dir)
    except Exception as exc:
        console.print(f"[red]descriptor registry not usable[/red] {exc}")
        raise typer.Exit(1) from exc


def _task_payload(dataset: Dataset, loaded) -> dict[str, object]:
    """Task identity plus resolved repository, digest and derived facts."""
    materialized = dataset.materialize(loaded)
    task = materialized.task
    body = task.task
    payload: dict[str, object] = {
        "uid": loaded.uid,
        "id": task.id,
        "version": task.version,
        "title": task.title,
        "category": task.category,
        "difficulty": task.difficulty,
        "evaluator": body.evaluator,
        "repository": {
            "source": body.repository.source,
            "ref": body.repository.ref,
            "kind": "seed" if is_seed_directory(body.repository.source) else "git",
        },
        "mutation": (
            {"patch": body.mutation.patch, "version": body.mutation.version}
            if body.mutation
            else None
        ),
        "snapshot_digest": loaded.digest,
        "path": str(loaded.path),
    }
    return payload


@dataset_app.command("list")
@handle_errors
def dataset_list_cmd(
    ctx: typer.Context,
    category: str | None = typer.Option(None, "--category", help="Only this category."),
    as_json: bool = JSON_OPTION,
) -> None:
    """List the tasks registered in the dataset."""
    context: CliContext = ctx.obj
    dataset = _dataset(context)
    tasks = [t for t in dataset if category is None or t.task.category == category]
    if as_json:
        show_json({"count": len(tasks), "tasks": [t.as_dict() for t in tasks]})
        return
    if not tasks:
        console.print("no tasks registered")
        return
    title = f"tasks in {build_app_paths(context.loaded().settings).datasets_dir}"
    table = Table(title=title, show_lines=False)
    table.add_column("id")
    table.add_column("version")
    table.add_column("category")
    table.add_column("difficulty")
    table.add_column("evaluator")
    table.add_column("mutation")
    for loaded in sorted(tasks, key=lambda t: (t.task.category, t.task.id)):
        table.add_row(
            loaded.task.id,
            loaded.task.version,
            loaded.task.category,
            loaded.task.difficulty,
            loaded.task.evaluator,
            "yes" if loaded.task.requires_mutation() else "no",
        )
    console.print(table)


@dataset_app.command("validate")
@handle_errors
def dataset_validate_cmd(
    ctx: typer.Context,
    check_repositories: bool = typer.Option(
        False, "--check-repositories", help="Also resolve each repository ref with git."
    ),
    verify_mutations: bool = typer.Option(
        False,
        "--verify-mutations",
        help="Run hidden tests to prove each mutation (base passes, mutated fails).",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Validate every task; exits 1 if any task fails its checks."""
    context: CliContext = ctx.obj
    dataset = _dataset(context)
    registry = _registry(context)
    report = dataset.validate(registry, check_repositories=check_repositories)

    if verify_mutations:
        paths = build_app_paths(context.loaded().settings)
        repos = RepositoryManager(paths.repositories_dir)
        workspaces = WorkspaceManager(repos, paths.workspaces_dir)
        verifier = MutationVerifier(workspaces)
        for result in report.tasks:
            if result.task_uid is None:
                continue
            try:
                loaded = dataset.require(result.task_uid)
            except TaskLoadError:
                continue
            verification = verifier.verify(loaded)
            if not verification.ok:
                hint = verification.details.get("hint")
                message = f"mutation verification: {verification.verdict.value}"
                result.fail(
                    "mutation_verified",
                    f"{message} ({hint})" if hint else message,
                )
            else:
                result.pass_check("mutation_verified", verification.verdict.value)

    if as_json:
        show_json(report.as_dict())
    else:
        for result in report.tasks:
            if result.ok:
                console.print(f"  [green]ok[/green]   {result.task_uid}")
            else:
                console.print(f"  [red]fail[/red] {result.task_uid}")
                for issue in result.issues:
                    console.print(f"      [dim]{issue}[/dim]")
        if report.ok:
            console.print(f"[green]all {len(report.tasks)} task(s) are valid[/green]")
        else:
            console.print(f"[red]{len(report.failed)} of {len(report.tasks)} task(s) failed[/red]")

    raise typer.Exit(0 if report.ok else 1)


@dataset_app.command("show")
@handle_errors
def dataset_show_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Task id or id@version."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show one task: descriptor, repository, digest and (optionally) mutation check."""
    context: CliContext = ctx.obj
    dataset = _dataset(context)
    try:
        loaded = dataset.require(reference)
    except TaskLoadError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    payload = _task_payload(dataset, loaded)
    if as_json:
        show_json(payload)
        return
    console.print(f"[bold]{loaded.uid}[/bold]")
    console.print(f"  title       {loaded.task.title or '—'}")
    console.print(f"  category    {loaded.task.category} ({loaded.task.difficulty})")
    console.print(f"  evaluator   {loaded.task.evaluator}")
    repository = payload["repository"]
    console.print(f"  repository  {repository['source']} @ {repository['ref']}")
    if loaded.task.requires_mutation():
        mutation = loaded.task.task.mutation
        console.print(f"  mutation    {mutation.patch} (v{mutation.version})")
    console.print(f"  snapshot    {loaded.digest}")


@dataset_app.command("prepare")
@handle_errors
def dataset_prepare_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Task id or id@version."),
    workspace_id: str = typer.Option("task-workspace", "--workspace-id"),
    no_mutation: bool = typer.Option(False, "--no-mutation", help="Prepare the base state only."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Create a per-task workspace from the pinned commit (mutation applied by default)."""
    context: CliContext = ctx.obj
    dataset = _dataset(context)
    try:
        loaded = dataset.require(reference)
    except TaskLoadError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    paths = build_app_paths(context.loaded().settings)
    repos = RepositoryManager(paths.repositories_dir)
    workspaces = WorkspaceManager(repos, paths.workspaces_dir)
    materialized = dataset.materialize(loaded)
    try:
        prepared = workspaces.prepare(
            materialized.task, workspace_id, task_dir=loaded.path, apply_mutation=not no_mutation
        )
    except Exception as exc:
        console.print(f"[red]workspace preparation failed[/red] {exc}")
        raise typer.Exit(1) from exc

    if as_json:
        show_json(prepared.as_dict())
        return
    console.print(f"[green]prepared[/green] {prepared.workspace_id}")
    console.print(f"  path         {prepared.path}")
    console.print(f"  base commit  {prepared.base_commit}")
    console.print(f"  tree         {prepared.tree}")
    console.print(f"  fingerprint  {prepared.fingerprint}")
    console.print(f"  mutation     {'applied' if prepared.mutation_applied else 'not applied'}")

"""Descriptor commands: list, validate and inspect registered components.

Adding an agent, plugin, model or category never changes this code: the
registry is discovered from the descriptor directory and every command works on
whatever that directory declares (implementation plan, section 9).
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from akbench.cli.common import EXIT_ERROR, CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths
from akbench.core.errors import DescriptorError
from akbench.descriptors import (
    AgentDescriptor,
    CategoryDescriptor,
    DescriptorKind,
    DescriptorRegistry,
    DimensionDescriptor,
    LoadedDescriptor,
    iter_descriptor_files,
    load_descriptor_file,
    load_registry,
)

descriptor_app = typer.Typer(
    help="List, validate and inspect component descriptors.",
    no_args_is_help=True,
)
agent_app = typer.Typer(help="Inspect registered agents.", no_args_is_help=True)
category_app = typer.Typer(help="Inspect registered task categories.", no_args_is_help=True)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")
KindOption = typer.Option(
    None,
    "--kind",
    help="Restrict to one kind: agent, runtime, plugin, model, category, evaluator, "
    "dimension or metric.",
)


def _descriptors_dir(context: CliContext) -> Path:
    return build_app_paths(context.loaded().settings).descriptors_dir


def _load(context: CliContext) -> DescriptorRegistry:
    """Load the descriptor directory, reporting an unusable directory as exit 1."""
    try:
        return load_registry(_descriptors_dir(context))
    except DescriptorError as exc:
        console.print(f"[red]descriptor directory is not usable[/red] {exc}")
        raise typer.Exit(EXIT_ERROR) from exc


def _resolve_kind(kind: str | None) -> DescriptorKind | None:
    if kind is None:
        return None
    try:
        return DescriptorKind(kind)
    except ValueError as exc:
        known = ", ".join(item.value for item in DescriptorKind)
        console.print(f"[red]unknown descriptor kind {kind!r}[/red] expected one of: {known}")
        raise typer.Exit(EXIT_ERROR) from exc


def _entry_dict(entry: LoadedDescriptor) -> dict[str, object]:
    return {
        "kind": entry.kind.value,
        "id": entry.snapshot.id,
        "version": entry.snapshot.version,
        "identity": entry.identity,
        "digest": entry.snapshot.digest,
        "source": str(entry.source) if entry.source else None,
    }


def _require(context: CliContext, kind: DescriptorKind, reference: str) -> LoadedDescriptor:
    try:
        return _load(context).require(kind, reference)
    except DescriptorError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_ERROR) from exc


@descriptor_app.command("list")
@handle_errors
def descriptor_list_cmd(
    ctx: typer.Context,
    kind: str | None = KindOption,
    as_json: bool = JSON_OPTION,
) -> None:
    """List every descriptor registered in the descriptor directory."""
    context: CliContext = ctx.obj
    resolved = _resolve_kind(kind)
    registry = _load(context)
    entries = registry.entries(resolved)
    directory = _descriptors_dir(context)

    if as_json:
        show_json(
            {
                "descriptors_dir": str(directory),
                "count": len(entries),
                "descriptors": [_entry_dict(entry) for entry in entries],
            }
        )
        return

    table = Table(title=f"descriptors in {directory}", show_lines=False)
    table.add_column("kind")
    table.add_column("id", overflow="fold")
    table.add_column("version")
    table.add_column("digest")
    for entry in entries:
        table.add_row(
            entry.kind.value,
            entry.snapshot.id,
            entry.snapshot.version,
            entry.snapshot.digest.removeprefix("sha256:")[:12],
        )
    console.print(table)


@descriptor_app.command("validate")
@handle_errors
def descriptor_validate_cmd(
    ctx: typer.Context,
    kind: str | None = KindOption,
    as_json: bool = JSON_OPTION,
) -> None:
    """Validate every descriptor file; exits 1 if any file is invalid.

    Files are validated one at a time so that a single broken descriptor cannot
    hide the verdict on the rest of the directory.
    """
    context: CliContext = ctx.obj
    directory = _descriptors_dir(context)
    if not directory.is_dir():
        console.print(f"[red]descriptor directory not found[/red] {directory}")
        if as_json:
            show_json(
                {
                    "descriptors_dir": str(directory),
                    "files": 0,
                    "ok": 0,
                    "failed": 0,
                    "results": [],
                }
            )
        raise typer.Exit(EXIT_ERROR)
    wanted = _resolve_kind(kind)
    kinds = [wanted] if wanted else list(DescriptorKind)

    results: list[dict[str, object]] = []
    for file_kind, path in iter_descriptor_files(directory, kinds):
        try:
            loaded = load_descriptor_file(path, file_kind)
            results.append(
                {
                    "file": _display_path(path, directory),
                    "kind": file_kind.value,
                    "status": "ok",
                    "count": len(loaded),
                    "error": None,
                }
            )
        except DescriptorError as exc:
            results.append(
                {
                    "file": _display_path(path, directory),
                    "kind": file_kind.value,
                    "status": "fail",
                    "count": 0,
                    "error": str(exc),
                }
            )

    failures = [result for result in results if result["status"] == "fail"]
    if as_json:
        show_json(
            {
                "descriptors_dir": str(directory),
                "files": len(results),
                "ok": len(results) - len(failures),
                "failed": len(failures),
                "results": results,
            }
        )
    else:
        for result in results:
            if result["status"] == "ok":
                console.print(f"  [green]ok[/green]   {result['file']} ({result['count']})")
            else:
                console.print(f"  [red]fail[/red] {result['file']}")
                console.print(f"      [dim]{result['error']}[/dim]")
        if failures:
            console.print(f"[red]{len(failures)} of {len(results)} file(s) failed[/red]")
        else:
            console.print(f"[green]all {len(results)} descriptor file(s) are valid[/green]")

    raise typer.Exit(EXIT_ERROR if failures else 0)


def _display_path(path: Path, directory: Path) -> str:
    """Path relative to the descriptor directory, so rows stay readable."""
    resolved = Path(path)
    if resolved.is_relative_to(directory):
        return str(resolved.relative_to(directory))
    return str(resolved)


def _show_payload(entry: LoadedDescriptor) -> dict[str, object]:
    """Descriptor content plus derived facts that matter when choosing a component."""
    payload: dict[str, object] = {
        "kind": entry.kind.value,
        "id": entry.snapshot.id,
        "version": entry.snapshot.version,
        "digest": entry.snapshot.digest,
        "source": str(entry.source) if entry.source else None,
        "descriptor": entry.snapshot.payload,
    }
    descriptor = entry.descriptor
    if isinstance(descriptor, AgentDescriptor):
        payload["capabilities"] = {
            name: {"status": status.value, "usable": status.usable}
            for name, status in sorted(descriptor.agent.capabilities.items())
        }
        payload["controllable_parameters"] = descriptor.controllable_parameters()
    elif isinstance(descriptor, DimensionDescriptor):
        payload["usable_as_factor"] = descriptor.usable_as_factor
        payload["allowed_values"] = descriptor.allowed_values()
    elif isinstance(descriptor, CategoryDescriptor):
        payload["enabled"] = descriptor.category.enabled
        payload["difficulties"] = descriptor.category.difficulties
    return payload


@descriptor_app.command("show")
@handle_errors
def descriptor_show_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Descriptor id or id@version."),
    kind: str = typer.Option(..., "--kind", help="Kind of the referenced descriptor."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show one descriptor: content, digest and derived facts."""
    context: CliContext = ctx.obj
    resolved = _resolve_kind(kind)
    if resolved is None:
        console.print("[red]--kind is required to show a descriptor[/red]")
        raise typer.Exit(EXIT_ERROR)
    entry = _require(context, resolved, reference)

    payload = _show_payload(entry)
    if as_json:
        show_json(payload)
        return

    console.print(f"[bold]{entry.kind.value}[/bold] {entry.identity}")
    console.print(f"  digest  {entry.snapshot.digest}")
    if entry.source:
        console.print(f"  source  {entry.source}")
    if "capabilities" in payload:
        _print_capabilities(payload["capabilities"])
        console.print(f"  controllable: {', '.join(payload['controllable_parameters']) or 'none'}")
    if "usable_as_factor" in payload:
        console.print(f"  usable_as_factor: {payload['usable_as_factor']}")
        console.print(f"  values: {payload['allowed_values'] or '—'}")


def _print_capabilities(capabilities: dict[str, dict[str, str]]) -> None:
    table = Table(title="capabilities", show_lines=False)
    table.add_column("capability")
    table.add_column("status")
    table.add_column("usable")
    for name, detail in capabilities.items():
        table.add_row(name, detail["status"], "yes" if detail["usable"] else "no")
    console.print(table)


@agent_app.command("list")
@handle_errors
def agent_list_cmd(
    ctx: typer.Context,
    as_json: bool = JSON_OPTION,
) -> None:
    """List agents registered through Agent Descriptors."""
    context: CliContext = ctx.obj
    entries = _load(context).entries(DescriptorKind.AGENT)
    if as_json:
        show_json({"count": len(entries), "agents": [_entry_dict(entry) for entry in entries]})
        return
    if not entries:
        console.print("no agents registered")
        return
    table = Table(title="agents", show_lines=False)
    table.add_column("id")
    table.add_column("version")
    table.add_column("adapter")
    table.add_column("execution")
    table.add_column("capabilities")
    for entry in entries:
        descriptor: AgentDescriptor = entry.descriptor  # type: ignore[assignment]
        usable = sum(1 for status in descriptor.agent.capabilities.values() if status.usable)
        table.add_row(
            entry.snapshot.id,
            entry.snapshot.version,
            descriptor.agent.adapter,
            descriptor.agent.execution_type.value,
            f"{usable}/{len(descriptor.agent.capabilities)} usable",
        )
    console.print(table)


@agent_app.command("inspect")
@handle_errors
def agent_inspect_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Agent id or id@version."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show one agent: capabilities with statuses, and controllable parameters."""
    context: CliContext = ctx.obj
    entry = _require(context, DescriptorKind.AGENT, reference)
    descriptor: AgentDescriptor = entry.descriptor  # type: ignore[assignment]

    payload = _show_payload(entry)
    if as_json:
        show_json(payload)
        return

    console.print(f"[bold]{entry.identity}[/bold] · adapter {descriptor.agent.adapter}")
    if descriptor.description:
        console.print(f"  {descriptor.description}")
    _print_capabilities(payload["capabilities"])  # type: ignore[arg-type,index]
    console.print(f"  controllable: {', '.join(payload['controllable_parameters']) or 'none'}")  # type: ignore[arg-type]
    if descriptor.agent.notes:
        console.print(f"  [dim]{descriptor.agent.notes}[/dim]")


@category_app.command("list")
@handle_errors
def category_list_cmd(
    ctx: typer.Context,
    as_json: bool = JSON_OPTION,
) -> None:
    """List task categories and whether experiments may use them."""
    context: CliContext = ctx.obj
    entries = _load(context).entries(DescriptorKind.CATEGORY)
    if as_json:
        show_json(
            {
                "count": len(entries),
                "categories": [
                    {
                        **_entry_dict(entry),
                        "enabled": _category_body(entry).enabled,
                        "difficulties": _category_body(entry).difficulties,
                    }
                    for entry in entries
                ],
            }
        )
        return
    if not entries:
        console.print("no categories registered")
        return
    table = Table(title="categories", show_lines=False)
    table.add_column("id")
    table.add_column("enabled")
    table.add_column("difficulties")
    for entry in entries:
        body = _category_body(entry)
        table.add_row(
            entry.snapshot.id,
            "[green]yes[/green]" if body.enabled else "[dim]no[/dim]",
            ", ".join(body.difficulties),
        )
    console.print(table)


def _category_body(entry: LoadedDescriptor) -> CategoryDescriptor:
    descriptor = entry.descriptor
    if not isinstance(descriptor, CategoryDescriptor):  # pragma: no cover - registry guarantees
        raise DescriptorError(f"{entry.identity} is not a category descriptor")
    return descriptor.category

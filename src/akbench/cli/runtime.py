"""Runtime commands: list, healthcheck, models and configuration reports.

Everything here works through the runtime registry and the manager contract;
no concrete runtime is named in this code. A runtime that cannot provide a
capability reports that capability as unsupported or unverified, with the
reason, instead of a silent pass.
"""

from __future__ import annotations

import json

import typer
from rich.table import Table

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths
from akbench.descriptors import DescriptorKind, RuntimeDescriptor, load_registry
from akbench.runtime import (
    LlmRouterAdapter,
    LlmRouterOptions,
    build_runtime_registry,
)

runtime_app = typer.Typer(
    help="Inspect and manage the runtimes registered for agents.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")
ConfigFileOption = typer.Option(
    None,
    "--config-file",
    help="Host-side model configuration file (only reachable from the router host).",
)


def _registry(context: CliContext):
    paths = build_app_paths(context.loaded().settings)
    try:
        descriptors = load_registry(paths.descriptors_dir)
    except Exception as exc:
        console.print(f"[red]descriptor registry not usable[/red] {exc}")
        raise typer.Exit(1) from exc
    return build_runtime_registry(
        [
            entry.descriptor
            for entry in descriptors.entries(DescriptorKind.RUNTIME)
            if isinstance(entry.descriptor, RuntimeDescriptor)
        ],
        allow_missing_adapter=True,
    )


def _manager(context: CliContext, reference: str, config_file: str | None = None):
    registry = _registry(context)
    try:
        runtime_id, version = _split_reference(reference)
    except ValueError as exc:
        console.print(f"[red]invalid runtime reference[/red] {exc}")
        raise typer.Exit(1) from exc
    try:
        entry = registry.resolve(runtime_id, version)
    except Exception as exc:
        console.print(f"[red]cannot resolve runtime[/red] {exc}")
        raise typer.Exit(1) from exc

    options = {}
    if config_file:
        from pathlib import Path

        options["config_file"] = Path(config_file)
    if options:
        manager = LlmRouterAdapter(entry.descriptor, LlmRouterOptions(**options))
    else:
        manager = entry.manager()
    return manager


def _split_reference(reference: str) -> tuple[str, str | None]:
    if "@" in reference:
        runtime_id, version = reference.split("@", 1)
        return runtime_id, version or None
    return reference, None


@runtime_app.command("list")
@handle_errors
def runtime_list_cmd(
    ctx: typer.Context,
    as_json: bool = JSON_OPTION,
) -> None:
    """List the runtimes registered from descriptors."""
    registry = _registry(ctx.obj)
    entries = registry.entries()
    if as_json:
        show_json(
            {
                "count": len(entries),
                "runtimes": [
                    {
                        "id": entry.id,
                        "version": entry.descriptor.version,
                        "adapter": entry.adapter_id,
                        "base_url": entry.descriptor.runtime.base_url,
                        "execution_modes": [
                            m.value for m in entry.descriptor.runtime.execution_modes
                        ],
                        "lifecycles": [
                            item.value for item in entry.descriptor.runtime.supported_lifecycles
                        ],
                        "required_env": entry.descriptor.runtime.required_env,
                    }
                    for entry in entries
                ],
            }
        )
        return
    if not entries:
        console.print("no runtimes registered")
        return
    table = Table(title="runtimes", show_lines=False)
    table.add_column("id")
    table.add_column("adapter")
    table.add_column("base_url")
    table.add_column("modes")
    table.add_column("lifecycles")
    for entry in entries:
        body = entry.descriptor.runtime
        table.add_row(
            entry.id,
            entry.adapter_id,
            body.base_url or "—",
            ", ".join(m.value for m in body.execution_modes),
            ", ".join(item.value for item in body.supported_lifecycles),
        )
    console.print(table)


@runtime_app.command("health")
@handle_errors
def runtime_health_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Runtime id or id@version."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Check the runtime's health endpoint and exit 1 if it is down."""
    manager = _manager(ctx.obj, reference)
    healthy = manager.healthcheck()
    payload = {
        "runtime": reference,
        "healthy": healthy,
        "base_url": getattr(manager, "base_url", None),
    }
    if as_json:
        show_json(payload)
        raise typer.Exit(0 if healthy else 1)
    mark = "[green]healthy[/green]" if healthy else "[red]unhealthy[/red]"
    console.print(f"{mark} {payload['runtime']} ({payload['base_url']})")
    raise typer.Exit(0 if healthy else 1)


@runtime_app.command("models")
@handle_errors
def runtime_models_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Runtime id or id@version."),
    as_json: bool = JSON_OPTION,
) -> None:
    """List the models the runtime serves (aliases are not included)."""
    manager = _manager(ctx.obj, reference)
    models = manager.list_models()
    if as_json:
        show_json(
            {
                "runtime": reference,
                "models": models,
                "note": None
                if models is not None
                else "the model inventory could not be read from this runtime",
            }
        )
        raise typer.Exit(0 if models is not None else 1)
    if models is None:
        console.print("[red]the model inventory could not be read[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{len(models)} model(s)[/bold] served by {reference}:")
    for model in models:
        console.print(f"  {model}")
    console.print(
        "  [dim]aliases are not listed by the router; the served inventory is not "
        "the full value space of the model dimension[/dim]"
    )


@runtime_app.command("config")
@handle_errors
def runtime_config_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Runtime id or id@version."),
    config_file: str | None = ConfigFileOption,
    as_json: bool = JSON_OPTION,
) -> None:
    """Report requested/effective/observed configuration with a trust level.

    The trust level is part of the answer: a runtime whose configuration cannot
    be read says so (plan section 13) instead of passing silently.
    """
    manager = _manager(ctx.obj, reference, config_file)
    report = manager.read_configuration()
    payload = report.as_dict()
    payload["runtime"] = reference
    if as_json:
        show_json(payload)
        raise typer.Exit(0)

    status = payload["verification_status"]
    color = "green" if status == "verified" else ("yellow" if status == "unverified" else "red")
    console.print(f"[{color}]configuration status: {status}[/{color}] ({reference})")
    if payload["effective_config"] is not None:
        preview = json.dumps(payload["effective_config"], ensure_ascii=False)[:200]
        console.print(f"  effective  {preview}")
    else:
        console.print("  effective  (unreadable)")
    for note in payload["notes"]:
        console.print(f"  [dim]{note}[/dim]")
    raise typer.Exit(0)


@runtime_app.command("state")
@handle_errors
def runtime_state_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Runtime id or id@version."),
    as_json: bool = JSON_OPTION,
) -> None:
    """A point-in-time snapshot of the runtime: health, models, metrics."""
    manager = _manager(ctx.obj, reference)
    state = manager.collect_runtime_state()
    payload = state.as_dict()
    payload["runtime"] = reference
    if as_json:
        show_json(payload)
        return
    mark = (
        "[green]healthy[/green]"
        if state.healthy
        else ("[red]unhealthy[/red]" if state.healthy is False else "[yellow]unknown[/yellow]")
    )
    console.print(f"{mark} {reference} ({state.base_url})")
    console.print(f"  lifecycle  {state.lifecycle.value if state.lifecycle else '—'}")
    console.print(f"  models     {len(state.models)} served")
    console.print(f"  metrics    {'available' if state.metrics_available else 'not available'}")
    raise typer.Exit(0 if state.healthy else 1)

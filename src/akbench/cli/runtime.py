"""Runtime commands: list, healthcheck, models and configuration reports.

Everything here works through the runtime registry and the manager contract;
no concrete runtime is named in this code. A runtime that cannot provide a
capability reports that capability as unsupported or unverified, with the
reason, instead of a silent pass.
"""

from __future__ import annotations

import json
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.table import Table

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths
from akbench.descriptors import DescriptorKind, RuntimeDescriptor, load_registry
from akbench.runtime import (
    Lifecycle,
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


# ------------------------------------------------------------ lifecycle

#: Where ``runtime start`` records the process it launched, so ``runtime stop``
#: can find it. The CLI is one-shot: an instance started outside a run outlives
#: the command that started it, and a state file is the whole bookkeeping.
INSTANCE_FILE = "manual-instance.json"


def _instance_file(context: CliContext, runtime_id: str) -> Path:
    paths = build_app_paths(context.loaded().settings)
    directory = paths.runtime_instances_dir / runtime_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory / INSTANCE_FILE


def _read_instance(context: CliContext, runtime_id: str) -> dict | None:
    path = _instance_file(context, runtime_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _require_managed(manager, reference: str) -> None:
    if getattr(manager, "lifecycle", None) is not Lifecycle.MANAGED:
        console.print(
            f"[red]cannot manage {reference}[/red] its lifecycle is external: "
            "AK-Bench does not start, stop or reconfigure a shared instance"
        )
        raise typer.Exit(2)


@runtime_app.command("start")
@handle_errors
def runtime_start_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Runtime id or id@version."),
    config_file: str | None = ConfigFileOption,
    as_json: bool = JSON_OPTION,
) -> None:
    """Start a managed instance outside a run, for manual verification.

    The instance belongs to this installation until ``runtime stop`` says
    otherwise: a managed run that wants the same endpoint refuses to start
    while something it did not launch answers there, which is the point.
    """
    context: CliContext = ctx.obj
    manager = _manager(context, reference, config_file)
    _require_managed(manager, reference)
    if _read_instance(context, reference) is not None:
        console.print(
            f"[yellow]{reference} already has a manually started instance[/yellow] "
            "`akbench runtime stop` stops it"
        )
        raise typer.Exit(1)
    manager.start()
    pid = getattr(manager, "_process", None)
    record = {
        "runtime": reference,
        "pid": pid.pid if pid is not None else None,
        "base_url": getattr(manager, "base_url", None),
        "log": str(getattr(manager, "log_path", None) or ""),
        "started_at": datetime.now(UTC).isoformat(),
    }
    _instance_file(context, reference).write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    if as_json:
        show_json(record)
        return
    console.print(f"[green]started[/green] {reference} ({record['base_url']})")
    if record["pid"]:
        console.print(f"  pid        {record['pid']}")
    if record["log"]:
        console.print(f"  log        {record['log']}")
    console.print(
        "  [dim]it keeps running after this command; `akbench runtime stop` stops it[/dim]"
    )


@runtime_app.command("stop")
@handle_errors
def runtime_stop_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Runtime id or id@version."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Stop the instance ``runtime start`` launched for this runtime."""
    context: CliContext = ctx.obj
    manager = _manager(context, reference)
    _require_managed(manager, reference)
    record = _read_instance(context, reference)
    if record is None:
        console.print(
            f"[red]no manually started instance of {reference}[/red] "
            "`akbench runtime start` starts one"
        )
        raise typer.Exit(1)
    pid = record.get("pid")
    stopped = False
    if isinstance(pid, int) and _process_alive(pid):
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 10
        while time.time() < deadline and _process_alive(pid):
            time.sleep(0.1)
        if _process_alive(pid):
            os.kill(pid, signal.SIGKILL)
        stopped = True
    _instance_file(context, reference).unlink(missing_ok=True)
    if as_json:
        show_json({"runtime": reference, "stopped": stopped, "pid": pid})
        return
    if stopped:
        console.print(f"[green]stopped[/green] {reference} (pid {pid})")
    else:
        console.print(
            f"[yellow]{reference} was not running[/yellow] (pid {pid}); the record was cleared"
        )


@runtime_app.command("verify")
@handle_errors
def runtime_verify_cmd(
    ctx: typer.Context,
    reference: str = typer.Argument(..., help="Runtime id or id@version."),
    expect: list[str] = typer.Option(
        [],
        "--expect",
        help="Expected effective configuration as name=value (repeatable).",
    ),
    config_file: str | None = ConfigFileOption,
    as_json: bool = JSON_OPTION,
) -> None:
    """Health, configuration triad and — when asked — the expected-vs-effective diff.

    A configuration that cannot be read is reported `unverified` or
    `unsupported`, never as a pass: plan rule 11 forbids counting the absence
    of evidence as evidence of agreement.
    """
    manager = _manager(ctx.obj, reference, config_file)
    healthy = manager.healthcheck()
    expected: dict[str, str] = {}
    for item in expect:
        name, _, value = item.partition("=")
        if not value:
            console.print(f"[red]--expect expects name=value[/red] got {item!r}")
            raise typer.Exit(1)
        expected[name] = value
    report = (
        manager.verify_configuration(expected)
        if expected
        else manager.read_configuration()
    )
    payload = report.as_dict()
    payload["runtime"] = reference
    payload["healthy"] = healthy
    if as_json:
        show_json(payload)
        raise typer.Exit(0 if healthy else 1)
    mark = "[green]healthy[/green]" if healthy else "[red]unhealthy[/red]"
    console.print(f"{mark} {reference} ({getattr(manager, 'base_url', None)})")
    status = payload["verification_status"]
    color = "green" if status == "verified" else ("yellow" if status == "unverified" else "red")
    console.print(f"  configuration  [{color}]{status}[/{color}]")
    for note in payload["notes"]:
        console.print(f"  [dim]{note}[/dim]")
    observed = payload.get("observed_config") or {}
    if observed.get("mismatches"):
        console.print(f"  [red]mismatches[/red] {json.dumps(observed['mismatches'])}")
    raise typer.Exit(0 if healthy else 1)


@runtime_app.command("status")
@handle_errors
def runtime_status_cmd(
    ctx: typer.Context,
    reference: str | None = typer.Argument(
        None, help="Runtime id; without it, every registered runtime."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Runtime status: one runtime in full (as `state`), or the whole registry."""
    context: CliContext = ctx.obj
    if reference is not None:
        manager = _manager(context, reference)
        state = manager.collect_runtime_state()
        record = _read_instance(context, reference)
        payload = state.as_dict()
        payload["runtime"] = reference
        payload["manually_started_pid"] = record.get("pid") if record else None
        if as_json:
            show_json(payload)
            raise typer.Exit(0 if state.healthy else 1)
        mark = (
            "[green]healthy[/green]"
            if state.healthy
            else ("[red]unhealthy[/red]" if state.healthy is False else "[yellow]unknown[/yellow]")
        )
        console.print(f"{mark} {reference} ({state.base_url})")
        console.print(f"  lifecycle  {state.lifecycle.value if state.lifecycle else '—'}")
        console.print(f"  models     {len(state.models)} served")
        if record:
            console.print(f"  instance   started manually, pid {record.get('pid')}")
        raise typer.Exit(0 if state.healthy else 1)

    registry = _registry(context)
    rows = []
    for entry in registry.entries():
        manager = entry.manager()
        state = manager.collect_runtime_state()
        rows.append(
            {
                "id": entry.id,
                "adapter": entry.adapter_id,
                "lifecycle": (
                    state.lifecycle.value if state.lifecycle is not None else "—"
                ),
                "healthy": state.healthy,
                "base_url": state.base_url or entry.descriptor.runtime.base_url or "—",
                "manual_pid": (_read_instance(context, entry.id) or {}).get("pid"),
            }
        )
    if as_json:
        show_json({"runtimes": rows})
        return
    table = Table(title="runtime status")
    table.add_column("id")
    table.add_column("lifecycle")
    table.add_column("health")
    table.add_column("base_url")
    table.add_column("manual")
    for row in rows:
        health = (
            "[green]healthy[/green]"
            if row["healthy"]
            else ("[red]unhealthy[/red]" if row["healthy"] is False else "[yellow]?[/yellow]")
        )
        table.add_row(
            row["id"],
            row["lifecycle"],
            health,
            row["base_url"],
            str(row["manual_pid"]) if row["manual_pid"] else "—",
        )
    console.print(table)

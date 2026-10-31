"""``akbench plugin``: observe and verify plugins from their descriptors.

Nothing here knows what a plugin does; the descriptor says which environment
variables may be observed and which verification methods exist, and the adapter
carries out the reading. Values are reported as observed, secrets as presence
only, and a plugin whose verification surface does not exist is reported as
unsupported rather than assumed to work (plan sections 10.1 and 10.2).
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from akbench.cli.common import CliContext, console, handle_errors, show_json
from akbench.config.loader import build_app_paths
from akbench.descriptors import DescriptorKind, PluginDescriptor, load_registry
from akbench.descriptors.plugin import ConfiguredValue
from akbench.plugins import build_plugin_registry
from akbench.plugins.contract import PluginReport

plugin_app = typer.Typer(
    help="Observe and verify the plugins AK-Bench is configured to measure.",
    no_args_is_help=True,
)

JSON_OPTION = typer.Option(False, "--json", help="Emit the result as JSON.")
EnvOption = typer.Option(
    [],
    "--env",
    help="Override one allowlisted variable as NAME=VALUE for this check (repeatable).",
)
ConfigFileOption = typer.Option(
    None,
    "--config-file",
    help="Host-side file holding the effective plugin configuration (JSON or YAML).",
)

STATUS_COLORS = {
    "verified": "green",
    "unverified": "yellow",
    "mismatch": "red",
    "unsupported": "magenta",
    "not_configured": "dim",
    "runtime_error": "red",
}


def _plugin_entries(context: CliContext) -> list:
    paths = build_app_paths(context.loaded().settings)
    registry = load_registry(paths.descriptors_dir)
    return list(registry.entries(DescriptorKind.PLUGIN))


def _select(entries: list, references: list[str]) -> list:
    """Filter descriptor entries by ``id`` or ``id@version``, keeping order."""
    if not references:
        return entries
    wanted = list(references)
    selected = []
    for item in entries:
        uid = item.descriptor.id
        if uid in wanted or f"{uid}@{item.descriptor.version}" in wanted:
            selected.append(item)
            matched = {uid, f"{uid}@{item.descriptor.version}"}
            wanted = [name for name in wanted if name not in matched]
    if wanted:
        console.print(f"[red]unknown plugin(s)[/red] {', '.join(wanted)}")
        raise typer.Exit(1)
    return selected


def _environment(overrides: list[str]) -> dict[str, str]:
    """Process environment plus the explicit overrides given on the command line."""
    import os

    env = dict(os.environ)
    for item in overrides:
        if "=" not in item:
            console.print(f"[red]--env expects NAME=VALUE[/red] got {item!r}")
            raise typer.Exit(1)
        name, _, value = item.partition("=")
        env[name.strip()] = value
    return env


def _read_effective_config(path: str) -> dict[str, object]:
    """Load the effective configuration file a caller supplied."""
    import yaml

    file_path = Path(path)
    if not file_path.is_file():
        console.print(f"[red]configuration file not found[/red] {file_path}")
        raise typer.Exit(1)
    try:
        payload = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        console.print(f"[red]configuration file is not valid JSON or YAML[/red] {exc}")
        raise typer.Exit(1) from exc
    if not isinstance(payload, dict):
        console.print("[red]configuration file must hold a mapping of name to value[/red]")
        raise typer.Exit(1)
    return payload


def _registry_for(
    descriptors: list[PluginDescriptor],
    config_file: str | None,
    plugin_id: str | None,
) -> tuple[object, bool]:
    """Build the adapter registry, wiring evidence only when it was supplied."""
    readers = {}
    if config_file:
        effective = _read_effective_config(config_file)
        target = plugin_id or (descriptors[0].id if descriptors else None)
        if target is not None:
            readers[target] = lambda: effective
    return build_plugin_registry(descriptors, config_readers=readers), bool(readers)


def _value_view(descriptor: PluginDescriptor, value: ConfiguredValue) -> dict[str, object]:
    """A display/JSON view that never carries a secret value."""
    entry = descriptor.benchmark.env(value.name)
    sensitive = bool(entry is not None and entry.sensitive)
    return {
        "name": value.name,
        "role": entry.role.value if entry else None,
        "requested": value.requested_value,
        "observed": None if sensitive else value.observed_value,
        "effective": None if sensitive else value.effective_value,
        "is_set": value.is_set,
        "sensitive": sensitive,
        "verification_status": value.verification_status.value,
        "value_source": value.value_source.value,
        "note": value.note,
    }


def _reports(
    context: CliContext,
    references: list[str],
    overrides: list[str],
    config_file: str | None,
) -> tuple[list[PluginReport], list[PluginDescriptor]]:
    entries = _select(_plugin_entries(context), references)
    descriptors = [item.descriptor for item in entries]
    digests = {item.descriptor.id: item.snapshot.digest for item in entries}
    registry, _ = _registry_for(descriptors, config_file, references[0] if references else None)
    reports = registry.reports(descriptors, environ=_environment(overrides), digests=digests)
    return reports, descriptors


@plugin_app.command("list")
@handle_errors
def plugin_list_cmd(ctx: typer.Context, as_json: bool = JSON_OPTION) -> None:
    """List the plugin descriptors this project ships."""
    context: CliContext = ctx.obj
    entries = _plugin_entries(context)
    if as_json:
        show_json(
            [
                {
                    **item.snapshot.as_dict(),
                    "provider": item.descriptor.plugin.provider,
                    "type": item.descriptor.plugin.type,
                    "capabilities": list(item.descriptor.plugin.capabilities),
                    "observed_env": len(item.descriptor.benchmark.observed_env),
                    "dimensions": item.descriptor.benchmark.dimension_names(),
                    "metrics": list(item.descriptor.benchmark.metrics),
                    "verification_required": item.descriptor.requires_verification,
                }
                for item in entries
            ]
        )
        return
    if not entries:
        console.print("[dim]no plugin descriptors[/dim]")
        return
    table = Table(title="Plugins")
    table.add_column("id", style="cyan")
    table.add_column("version")
    table.add_column("provider")
    table.add_column("type")
    table.add_column("env", justify="right")
    table.add_column("dimensions")
    table.add_column("metrics", justify="right")
    for item in entries:
        descriptor: PluginDescriptor = item.descriptor
        table.add_row(
            descriptor.id,
            descriptor.version,
            descriptor.plugin.provider,
            descriptor.plugin.type,
            str(len(descriptor.benchmark.observed_env)),
            ", ".join(descriptor.benchmark.dimension_names()) or "—",
            str(len(descriptor.benchmark.metrics)),
        )
    console.print(table)


@plugin_app.command("status")
@handle_errors
def plugin_status_cmd(
    ctx: typer.Context,
    references: list[str] = typer.Argument(None, help="Plugin id or id@version (default all)."),
    env: list[str] = EnvOption,
    as_json: bool = JSON_OPTION,
) -> None:
    """Report the observed configuration of each plugin, secrets as presence only."""
    context: CliContext = ctx.obj
    reports, descriptors = _reports(context, references, env, None)
    by_id = {descriptor.id: descriptor for descriptor in descriptors}

    if as_json:
        show_json(
            [
                {
                    **report.as_dict(),
                    "values": [_value_view(by_id[report.plugin_id], value) for value in
                               (report.state.values if report.state else [])],
                }
                for report in reports
            ]
        )
        return

    for report in reports:
        descriptor = by_id[report.plugin_id]
        color = STATUS_COLORS.get(
            report.state.verification_status.value if report.state else "unverified", "white"
        )
        enabled = "on" if report.enabled else "off"
        console.print(
            f"[bold]{report.plugin_id}[/bold] v{report.plugin_version} "
            f"[{color}]{report.state.verification_status.value if report.state else 'unknown'}[/]"
            f" · {enabled}"
        )
        if report.note:
            console.print(f"  [dim]{report.note}[/dim]")
        values = report.state.values if report.state else []
        shown = [value for value in values if value.is_set or value.requested_value is not None]
        for value in shown:
            view = _value_view(descriptor, value)
            observed = "set" if view["sensitive"] and view["is_set"] else view["observed"]
            status = value.verification_status.value
            console.print(
                f"  {value.name:<58} {observed!s:<12} "
                f"[{STATUS_COLORS.get(status, 'white')}]{status}[/]"
                + (f" — {value.note}" if value.note else "")
            )
        unavailable = [metric for metric in report.metrics if not metric.available]
        if unavailable:
            console.print(
                f"  [dim]{len(unavailable)} plugin metric(s) unavailable: "
                + ", ".join(metric.name for metric in unavailable)
                + "[/dim]"
            )


@plugin_app.command("verify")
@handle_errors
def plugin_verify_cmd(
    ctx: typer.Context,
    references: list[str] = typer.Argument(None, help="Plugin id or id@version (default all)."),
    env: list[str] = EnvOption,
    config_file: str | None = ConfigFileOption,
    as_json: bool = JSON_OPTION,
) -> None:
    """Verify a plugin against available evidence, and say what evidence is missing.

    A plugin is ``verified`` only when its requested values match an effective
    configuration that could actually be read (``--config-file``, host-side).
    Without it the answer is ``unsupported`` — presence of environment
    variables is not proof a plugin works (plan 10.2).
    """
    context: CliContext = ctx.obj
    reports, descriptors = _reports(context, references, env, config_file)
    by_id = {descriptor.id: descriptor for descriptor in descriptors}

    if as_json:
        show_json(
            [
                {
                    "plugin": report.plugin_id,
                    "version": report.plugin_version,
                    "verification_status": (
                        report.state.verification_status.value if report.state else "unverified"
                    ),
                    "methods_declared": by_id[report.plugin_id].benchmark.verification.methods,
                    "evidence": "effective configuration file" if config_file else None,
                    "note": report.note,
                    "mismatches": [
                        value.name
                        for value in (report.state.values if report.state else [])
                        if value.verification_status.value == "mismatch"
                    ],
                }
                for report in reports
            ]
        )
        return

    for report in reports:
        descriptor = by_id[report.plugin_id]
        state = report.state
        status = state.verification_status.value if state else "unverified"
        console.print(
            f"[bold]{report.plugin_id}[/bold] [{STATUS_COLORS.get(status, 'white')}]{status}[/]"
        )
        methods = ", ".join(descriptor.benchmark.verification.methods) or "—"
        evidence = "effective configuration file" if config_file else "none"
        console.print(f"  declared methods  {methods}")
        console.print(f"  evidence used     {evidence}")
        if report.note:
            console.print(f"  [dim]{report.note}[/dim]")
    raise typer.Exit(0)

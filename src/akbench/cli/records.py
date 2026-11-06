"""Shared record handling for the commands that store runs in the history.

Both ``akbench run single --store`` and ``akbench experiment run`` need the
same thing: write the run record, observe the plugin state, build the
reproducibility manifest, and register the artifacts. Keeping it in one place
is what makes the two paths agree about what a stored run is.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from akbench.cli.common import CliContext
from akbench.config.loader import build_app_paths, resolve_database_url
from akbench.config.models import Settings
from akbench.descriptors import DescriptorKind, PluginDescriptor, load_registry
from akbench.plugins import build_plugin_registry
from akbench.storage.db import create_db_engine
from akbench.storage.history import HistoryStore
from akbench.storage.manifest import build_manifest
from akbench.storage.migrator import upgrade


def write_record(path: Path, record: dict[str, object]) -> None:
    """Write one run record as indented JSON, creating the directory tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, indent=2, ensure_ascii=False, default=str)
    path.write_text(payload + "\n", encoding="utf-8")


def plugin_reports(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    environ_applied: bool = False,
) -> list[dict[str, object]]:
    """Observe the shipped plugin descriptors; never contact the router.

    The verification status travels with the report, so a stored
    ``unverified`` stays unverified in the history rather than reading as a
    confirmed configuration.

    ``environ`` is the environment to read instead of this process's own. A
    run that started its own runtime must report the environment **that
    process** was launched with (``record["runtime_environment"]``); reading
    the CLI's environment instead would describe a process that is not the
    one under test. ``environ_applied`` carries that distinction to the
    adapter, which then reports ``unverified`` (applied, effect not yet
    confirmed) rather than ``unsupported``.
    """
    try:
        paths = build_app_paths(settings)
        registry = load_registry(paths.descriptors_dir)
    except Exception:  # a missing descriptor tree must not fail a run
        return []
    descriptors = [entry.descriptor for entry in registry.entries(DescriptorKind.PLUGIN)]
    digests = registry.digest_map(DescriptorKind.PLUGIN)
    if not descriptors:
        return []
    # A row is a statement about a plugin the run configured. A run that named
    # no pipeline and set no toggle said nothing about a plugin, so there is
    # nothing to verify and no row is recorded: an ``unverified`` line for a
    # plugin the process never loaded reads as a defect that does not exist.
    relevant = _plugins_the_run_configured(descriptors, environ)
    return [
        report.as_dict()
        for report in build_plugin_registry(relevant).reports(
            relevant,
            digests=digests,
            environ=environ,
            environ_applied=environ_applied,
        )
    ]


#: The variable that names the plugin pipeline a router process loads at start.
PIPELINE_ENV = "LLM_ROUTER_UTILS_PLUGINS_PIPELINE"


def _plugins_the_run_configured(
    descriptors: list[PluginDescriptor], environ: Mapping[str, str] | None
) -> list[PluginDescriptor]:
    """The descriptors this run engaged, read from the environment it observed.

    A plugin belongs to a run only when the run says so: its id is named in the
    pipeline the process loads (``LLM_ROUTER_UTILS_PLUGINS_PIPELINE``), or its
    own ``benchmark.enabled_when`` toggle is set in that environment. A plugin
    that ships with the installation and was named by neither is not part of
    the run, and a row about it would only be noise.
    """
    environment = dict(environ or {})
    pipeline = {
        part.strip()
        for part in environment.get(PIPELINE_ENV, "").split(",")
        if part.strip()
    }
    selected: list[PluginDescriptor] = []
    for descriptor in descriptors:
        toggle = descriptor.benchmark.enabled_when
        if descriptor.id in pipeline or (toggle is not None and toggle in environment):
            selected.append(descriptor)
    return selected


def _launched_environment(record: dict[str, object]) -> dict[str, str] | None:
    """The environment this run started its runtime with, as strings."""
    declared = record.get("runtime_environment")
    if not isinstance(declared, dict) or not declared:
        return None
    environment = {
        str(name): str(value)
        for name, value in declared.items()
        if isinstance(value, (str, int, float, bool))
    }
    return environment or None


def component_descriptors(
    settings: Settings, *, agent_id: str | None, runtime_id: str | None
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    """What the run's agent and runtime said about themselves, as stored payloads.

    A run names its components by id; the descriptors under ``descriptors/``
    are what those ids mean — capabilities, controllable configuration, the
    endpoints and environment a runtime is launched with. Both are returned in
    the shape :meth:`HistoryStore.record_run` stores, with the file text kept
    beside the parsed identity, and either is ``None`` when the run did not
    name it or the registry does not carry it. A missing descriptor tree is a
    missing fact, not a failed run.
    """
    try:
        paths = build_app_paths(settings)
        registry = load_registry(paths.descriptors_dir)
    except Exception:
        return None, None
    agent = _descriptor_payload(registry, DescriptorKind.AGENT, agent_id)
    runtime = _descriptor_payload(registry, DescriptorKind.RUNTIME, runtime_id)
    return agent, runtime


def _descriptor_payload(
    registry: object, kind: DescriptorKind, descriptor_id: str | None
) -> dict[str, object] | None:
    """One descriptor of ``kind``, resolved by id, with the file it was written in."""
    if not descriptor_id:
        return None
    entry = registry.get(kind, descriptor_id)  # type: ignore[attr-defined]
    if entry is None:
        return None
    payload = dict(entry.snapshot.payload)
    payload["kind"] = kind.value
    if entry.source is not None:
        try:
            payload["descriptor_yaml"] = Path(entry.source).read_text(encoding="utf-8")
        except OSError:
            pass
    return payload


def store_run(
    context: CliContext,
    record: dict[str, object],
    *,
    loaded: object,
    artifacts_dir: Path,
    experiment_uid: str | None,
    agent_id: str,
    agent_parameters: dict[str, object],
    variant_uid: str | None = None,
    repetition: int | None = None,
) -> dict[str, object]:
    """Record the run, its artifacts and the plugin state in the history.

    The plugin state is observed from the environment the run's runtime was
    launched with when the run started one; for an external router, where no
    launch happened, this process's environment is all that can honestly be
    said about it, and the report says so.
    """
    settings = context.loaded().settings
    url = resolve_database_url(settings)
    upgrade(url)
    store = HistoryStore(create_db_engine(url))

    uid = experiment_uid or f"adhoc/{agent_id}"
    # A uid that has no experiment row yet is created here; a uid that was
    # planned keeps the title, descriptor and configuration hash the plan set,
    # because re-storing must not erase the history it belongs to.
    existing = store.experiments()
    known = any(row.get("uid") == uid for row in existing)
    if known:
        store.record_plan(experiment_uid=uid)
    else:
        store.record_plan(experiment_uid=uid, title=f"adhoc runs of {agent_id}")

    # A run that launched its own runtime knows that process's environment;
    # observing this CLI process instead would report the toggles of a process
    # that never served the run (the bug this line fixes).
    launched = _launched_environment(record)
    reports = plugin_reports(settings, environ=launched, environ_applied=launched is not None)
    plugin_versions = {
        str(report["plugin_id"]): str(report.get("plugin_version", "")) for report in reports
    }

    # The orchestrator records the parameters it actually handed the adapter,
    # defaults from the agent descriptor included; the caller's dict is the
    # fallback for records produced elsewhere.
    applied = record.get("agent_parameters")
    if not isinstance(applied, dict) or not applied:
        applied = agent_parameters
    manifest = build_manifest(
        record,
        experiment_uid=uid,
        variant_uid=variant_uid,
        task=loaded,
        adapter_id="codex",
        plugin_versions=plugin_versions,
        execution_parameters={
            "mode": record.get("mode"),
            "runtime": record.get("runtime_id"),
            "agent_parameters": applied,
        },
    )
    manifest_path = artifacts_dir / "manifest.json"
    write_record(manifest_path, manifest.as_dict())
    record["manifest_digest"] = manifest.digest

    agent_descriptor, runtime_descriptor = component_descriptors(
        settings,
        agent_id=str(record.get("agent_id") or agent_id),
        runtime_id=str(record["runtime_id"]) if record.get("runtime_id") else None,
    )
    stored = store.record_run(
        record,
        experiment_uid=uid,
        variant_uid=variant_uid,
        task=loaded,
        repetition=repetition,
        agent_descriptor=agent_descriptor,
        runtime_descriptor=runtime_descriptor,
    )
    if reports:
        store.record_plugin_observations(str(stored["run_uid"]), reports)

    paths_to_register = [manifest_path]
    if artifacts_dir.is_dir():
        for candidate in sorted(artifacts_dir.iterdir()):
            if candidate.is_file() and candidate != manifest_path:
                paths_to_register.append(candidate)
    evaluation = record.get("evaluation")
    if isinstance(evaluation, dict):
        artifacts = evaluation.get("artifacts")
        if isinstance(artifacts, dict):
            paths_to_register.extend(
                value for value in artifacts.values() if isinstance(value, str)
            )
    registered = store.register_artifacts(
        str(stored["run_uid"]), [path for path in paths_to_register if Path(path).is_file()]
    )
    # The record is re-written after storage because the stored row carries the
    # manifest digest; it is registered afterwards, so the stored checksum
    # covers the file the reader will actually verify.
    write_record(artifacts_dir / "run_record.json", record)
    registered.extend(
        store.register_artifacts(str(stored["run_uid"]), [artifacts_dir / "run_record.json"])
    )
    store.record_events(
        [
            {
                "event_type": "stored",
                "message": (
                    f"recorded with {len(registered)} artifact(s)"
                    + (f", repetition {repetition}" if repetition is not None else "")
                ),
            }
        ],
        run_uid=str(stored["run_uid"]),
        experiment_uid=uid,
    )
    return {
        "experiment_uid": uid,
        "run_uid": stored["run_uid"],
        "manifest_digest": manifest.digest,
        "manifest_complete": manifest.complete,
        "artifacts_registered": len(registered),
    }

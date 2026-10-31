"""Shared record handling for the commands that store runs in the history.

Both ``akbench run single --store`` and ``akbench experiment run`` need the
same thing: write the run record, observe the plugin state, build the
reproducibility manifest, and register the artifacts. Keeping it in one place
is what makes the two paths agree about what a stored run is.
"""

from __future__ import annotations

import json
from pathlib import Path

from akbench.cli.common import CliContext
from akbench.config.loader import build_app_paths, resolve_database_url
from akbench.config.models import Settings
from akbench.descriptors import DescriptorKind, load_registry
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


def plugin_reports(settings: Settings) -> list[dict[str, object]]:
    """Observe the shipped plugin descriptors; never contact the router.

    The verification status travels with the report, so a stored
    ``unverified`` stays unverified in the history rather than reading as a
    confirmed configuration.
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
    return [
        report.as_dict()
        for report in build_plugin_registry(descriptors).reports(descriptors, digests=digests)
    ]


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

    The plugin state is observed from the environment of this process, which
    is all a benchmark on an external router can honestly say about it.
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

    reports = plugin_reports(settings)
    plugin_versions = {
        str(report["plugin_id"]): str(report.get("plugin_version", "")) for report in reports
    }

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
            "agent_parameters": agent_parameters,
        },
    )
    manifest_path = artifacts_dir / "manifest.json"
    write_record(manifest_path, manifest.as_dict())
    record["manifest_digest"] = manifest.digest

    stored = store.record_run(
        record,
        experiment_uid=uid,
        variant_uid=variant_uid,
        task=loaded,
        repetition=repetition,
    )
    if reports:
        store.record_plugin_observations(str(stored["run_uid"]), reports)

    paths_to_register = [manifest_path]
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

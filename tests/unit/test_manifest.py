"""The reproducibility manifest: what a run was, and what it could not state.

A manifest must never fill a gap with a plausible guess. These tests guard the
two edges: the digest is stable and derived only from the stated facts, and the
``complete``/``unknown_fields`` pair makes an incomplete manifest say so.
"""

from __future__ import annotations

from types import SimpleNamespace

from akbench.storage.manifest import REQUIRED_FIELDS, build_manifest


def _task_stub() -> SimpleNamespace:
    repository = SimpleNamespace(source="https://example.test/wc.git", ref="abc1234")
    body = SimpleNamespace(repository=repository)
    descriptor = SimpleNamespace(id="wordcount-001", version="1.0.0", task=body)
    return SimpleNamespace(uid="wordcount-001@1.0.0", digest="sha256:task", task=descriptor)


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "run_uid": "run-1",
        "task_uid": "wordcount-001@1.0.0",
        "agent_id": "codex",
        "agent_version": "0.42.0",
        "runtime_id": "llm-router",
    }
    record.update(overrides)
    return record


def test_manifest_reads_the_task_from_the_loaded_task_not_the_record() -> None:
    manifest = build_manifest(
        _record(),
        experiment_uid="demo@1.0.0",
        task=_task_stub(),
        adapter_id="codex",
        config_hash="sha256:cfg",
    )

    assert manifest.task_uid == "wordcount-001@1.0.0"
    assert manifest.task_version == "1.0.0"
    assert manifest.task_digest == "sha256:task"
    assert manifest.repository_source == "https://example.test/wc.git"
    assert manifest.repository_commit == "abc1234"


def test_manifest_digest_is_stable_and_only_from_stated_facts() -> None:
    first = build_manifest(
        _record(), experiment_uid="demo@1.0.0", task=_task_stub(), config_hash="sha256:cfg"
    )
    second = build_manifest(
        _record(), experiment_uid="demo@1.0.0", task=_task_stub(), config_hash="sha256:cfg"
    )
    other = build_manifest(
        _record(), experiment_uid="demo@2.0.0", task=_task_stub(), config_hash="sha256:cfg"
    )

    assert first.digest == second.digest
    assert first.digest.startswith("sha256:")
    assert first.digest != other.digest


def test_complete_manifest_lists_no_unknown_fields() -> None:
    manifest = build_manifest(
        _record(agent_version="0.42.0"),
        experiment_uid="demo@1.0.0",
        variant_uid="v-1",
        task=_task_stub(),
        adapter_id="codex",
        config_hash="sha256:cfg",
        plugin_versions={"agentic-knowledge": "1.2.0"},
        descriptor_digests={"agent:codex@1.0.0": "sha256:agent"},
        sandbox_image="ak-bench/sandbox:0.1",
    )

    assert manifest.complete is True
    assert manifest.unknown_fields == []


def test_incomplete_manifest_names_what_it_could_not_state() -> None:
    manifest = build_manifest(_record())

    assert manifest.complete is False
    for name in REQUIRED_FIELDS:
        if getattr(manifest, name) is None:
            assert name in manifest.unknown_fields
    assert "variant_uid" in manifest.unknown_fields
    assert "config_hash" in manifest.unknown_fields
    assert "plugin_versions" in manifest.unknown_fields


def test_as_dict_round_trips_the_identity_facts() -> None:
    manifest = build_manifest(
        _record(),
        experiment_uid="demo@1.0.0",
        task=_task_stub(),
        adapter_id="codex",
        config_hash="sha256:cfg",
    )

    payload = manifest.as_dict()
    assert payload["digest"] == manifest.digest
    assert payload["task"]["uid"] == "wordcount-001@1.0.0"
    assert payload["repository"]["commit"] == "abc1234"
    assert payload["agent"] == {"id": "codex", "version": "0.42.0", "adapter": "codex"}
    assert payload["complete"] is False

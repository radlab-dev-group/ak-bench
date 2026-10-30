"""Registry behaviour: discovery, versioned identity, digests, conflicts."""

from __future__ import annotations

from pathlib import Path

import pytest

from akbench.core.errors import DescriptorError
from akbench.descriptors import (
    DescriptorKind,
    DescriptorRegistry,
    MetricDescriptor,
    PluginDescriptor,
    compute_digest,
    iter_descriptor_files,
    load_descriptor_file,
    load_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_DESCRIPTORS = REPO_ROOT / "descriptors"


@pytest.fixture
def registry() -> DescriptorRegistry:
    return DescriptorRegistry()


@pytest.fixture
def descriptor_tree(tmp_path: Path) -> Path:
    """A scratch descriptor directory with two kinds."""
    (tmp_path / "models").mkdir(parents=True)
    (tmp_path / "agents").mkdir()
    (tmp_path / "models" / "one.yaml").write_text(
        'schema_version: "1.0"\nid: m1\nversion: "1.0.0"\nmodel:\n  provider: p\n',
        encoding="utf-8",
    )
    (tmp_path / "agents" / "a.yaml").write_text(
        'schema_version: "1.0"\nid: agent-a\nversion: "1.0.0"\nagent:\n  adapter: x\n',
        encoding="utf-8",
    )
    return tmp_path


def test_directory_name_selects_the_kind(descriptor_tree: Path) -> None:
    registry = load_registry(descriptor_tree)
    assert registry.get(DescriptorKind.MODEL, "m1") is not None
    assert registry.get(DescriptorKind.AGENT, "agent-a") is not None
    # a model is never resolvable as an agent, and vice versa
    assert registry.get(DescriptorKind.AGENT, "m1") is None


def test_unknown_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DescriptorError):
        load_registry(tmp_path / "nope")


def test_multi_document_file_registers_every_entry(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "many.yaml").write_text(
        'id: m1\nversion: "1"\n---\nid: m2\nversion: "1"\n',
        encoding="utf-8",
    )
    registry = load_registry(tmp_path)
    assert set(registry.ids(DescriptorKind.MODEL)) == {"m1", "m2"}


def test_list_shape_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "list.yaml").write_text(
        "- id: m1\n  version: '1'\n- id: m2\n  version: '1'\n",
        encoding="utf-8",
    )
    assert len(load_registry(tmp_path)) == 2


def test_non_mapping_root_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "bad.yaml").write_text("- just\n- strings\n", encoding="utf-8")
    with pytest.raises(DescriptorError):
        load_registry(tmp_path)


def test_digest_is_stable_across_loads_and_field_order(descriptor_tree: Path) -> None:
    first = load_registry(descriptor_tree).require(DescriptorKind.MODEL, "m1")
    rewritten = descriptor_tree / "models" / "sorted.yaml"
    rewritten.write_text(
        'version: "1.0.0"\nid: m1\nschema_version: "1.0"\nmodel:\n  provider: p\n',
        encoding="utf-8",
    )
    descriptor_tree.joinpath("models", "one.yaml").unlink()
    second = load_registry(descriptor_tree).require(DescriptorKind.MODEL, "m1")
    assert first.snapshot.digest == second.snapshot.digest


def test_compute_digest_is_canonical() -> None:
    assert compute_digest({"a": 1, "b": 2}) == compute_digest({"b": 2, "a": 1})
    assert compute_digest({"a": 1}).startswith("sha256:")


def test_same_id_different_content_is_a_conflict(descriptor_tree: Path) -> None:
    registry = load_registry(descriptor_tree)
    with pytest.raises(DescriptorError, match="conflicting"):
        registry.add_raw(
            DescriptorKind.MODEL,
            {"id": "m1", "version": "1.0.0", "model": {"provider": "different"}},
        )


def test_re_registering_identical_content_is_idempotent(descriptor_tree: Path) -> None:
    registry = load_registry(descriptor_tree)
    before = len(registry)
    first = registry.require(DescriptorKind.MODEL, "m1")
    second = registry.add(first.descriptor, DescriptorKind.MODEL)
    assert first.snapshot.digest == second.snapshot.digest
    assert len(registry) == before


def test_multiple_versions_of_one_id_resolve_explicitly(registry: DescriptorRegistry) -> None:
    registry.add_raw(DescriptorKind.MODEL, {"id": "m", "version": "1.0.0"})
    registry.add_raw(DescriptorKind.MODEL, {"id": "m", "version": "1.2.0"})
    registry.add_raw(DescriptorKind.MODEL, {"id": "m", "version": "1.10.0"})

    assert registry.require(DescriptorKind.MODEL, "m").snapshot.version == "1.10.0"
    assert registry.require(DescriptorKind.MODEL, "m@1.2.0").snapshot.version == "1.2.0"
    assert len(registry.versions(DescriptorKind.MODEL, "m")) == 3


def test_require_reports_registered_ids(registry: DescriptorRegistry) -> None:
    registry.add_raw(DescriptorKind.MODEL, {"id": "known", "version": "1"})
    with pytest.raises(DescriptorError, match="known"):
        registry.require(DescriptorKind.MODEL, "missing")


def test_digest_map_is_what_an_experiment_pins(registry: DescriptorRegistry) -> None:
    registry.add_raw(DescriptorKind.MODEL, {"id": "m", "version": "1.0.0"})
    digest_map = registry.digest_map(DescriptorKind.MODEL)
    assert digest_map == {
        "model:m@1.0.0": registry.require(DescriptorKind.MODEL, "m").snapshot.digest
    }


def test_unknown_kind_has_no_model() -> None:
    with pytest.raises(DescriptorError):
        DescriptorRegistry(models={}).model_for(DescriptorKind.AGENT)


def test_invalid_descriptor_names_the_kind_and_field(descriptor_tree: Path) -> None:
    with pytest.raises(DescriptorError, match="model descriptor"):
        load_registry(descriptor_tree).add_raw(
            DescriptorKind.MODEL,
            {"id": "x", "version": "1", "model": {"context_window": 0}},
        )


def test_load_descriptor_file_validates_one_file_alone(descriptor_tree: Path) -> None:
    path = descriptor_tree / "models" / "one.yaml"
    assert len(load_descriptor_file(path, DescriptorKind.MODEL)) == 1
    # a file from another kind fails when read with the wrong kind
    with pytest.raises(DescriptorError):
        load_descriptor_file(descriptor_tree / "agents" / "a.yaml", DescriptorKind.MODEL)


def test_iter_descriptor_files_maps_files_to_kinds(descriptor_tree: Path) -> None:
    found = {path.name: kind for kind, path in iter_descriptor_files(descriptor_tree)}
    assert found["one.yaml"] == DescriptorKind.MODEL
    assert found["a.yaml"] == DescriptorKind.AGENT


def test_shipped_descriptors_all_load_and_validate() -> None:
    """The descriptors shipped in this repository must always be loadable."""
    registry = load_registry(SHIPPED_DESCRIPTORS)
    assert registry.get(DescriptorKind.AGENT, "codex") is not None
    assert registry.get(DescriptorKind.RUNTIME, "llm-router") is not None
    assert registry.get(DescriptorKind.PLUGIN, "agentic_knowledge") is not None
    assert len(registry) >= 20


def test_shipped_metrics_explain_why_they_are_unavailable() -> None:
    """An unavailable metric without a reason would silently become a guess."""
    registry = load_registry(SHIPPED_DESCRIPTORS)
    for entry in registry.entries(DescriptorKind.METRIC):
        descriptor: MetricDescriptor = entry.descriptor  # type: ignore[assignment,no-redef]
        if not descriptor.computable:
            assert descriptor.metric.unavailable_reason, f"{entry.identity} lacks a reason"


def test_shipped_plugin_descriptors_use_only_verified_env_names() -> None:
    """Every allowlisted ENV name must look real, never be a placeholder."""
    registry = load_registry(SHIPPED_DESCRIPTORS)
    for entry in registry.entries(DescriptorKind.PLUGIN):
        descriptor: PluginDescriptor = entry.descriptor  # type: ignore[assignment,no-redef]
        for env in descriptor.benchmark.observed_env:
            assert env.name.isupper()
            assert "ACTUAL" not in env.name

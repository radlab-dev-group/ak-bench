"""A memory run must check out under the name the knowledge plugin scopes by.

The plugin decides which collection a request reads from the basename of the
working directory the agent declares. AK-Bench names a workspace after the
run, so an unguided replay reads a collection its learning run never wrote.
These tests pin the rule the experiment runner applies: a memory run's
checkout is named after the repository, its parent is named after the run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from akbench.cli.experiments import _knowledge_workspace_id
from akbench.experiments import load_experiment_file
from akbench.knowledge.modes import KnowledgeMode
from akbench.knowledge.planning import MemoryPlanBuilder

REPO_ROOT = Path(__file__).resolve().parents[2]
ATLAS = REPO_ROOT / "configs" / "experiments" / "knowledge-replay-atlas.yaml"


@pytest.fixture
def dataset():
    from akbench.datasets import Dataset

    return Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)


@pytest.fixture
def plugin():
    from akbench.descriptors import DescriptorKind, load_registry

    registry = load_registry(REPO_ROOT / "descriptors")
    return next(
        item.descriptor
        for item in registry.entries(DescriptorKind.PLUGIN)
        if item.descriptor.id == "agentic_knowledge"
    )


def _pin(experiment, task_uid: str, repetition: int = 0) -> str | None:
    return _knowledge_workspace_id(
        experiment,
        agent_id="codex",
        task_uid=task_uid,
        variant_id="default",
        repetition=repetition,
        repository_source="datasets/_sources/atlas",
    )


def test_a_memory_checkout_is_named_after_the_repository_it_scopes_by() -> None:
    experiment = load_experiment_file(ATLAS)
    pinned = _pin(experiment, "atlas-drift-001@1.0.0")
    assert pinned is not None
    assert Path(pinned).name == "atlas"


def test_arms_of_one_fixture_share_the_scope_and_not_the_directory() -> None:
    experiment = load_experiment_file(ATLAS)
    learning = _pin(experiment, "atlas-drift-001@1.0.0")
    twin = _pin(experiment, "atlas-drift-003@1.0.0")
    again = _pin(experiment, "atlas-drift-001@1.0.0", repetition=1)
    # One collection for the whole family: the transfer scenario can read the
    # learning arm's knowledge at all.
    assert Path(learning).name == Path(twin).name == "atlas"
    # And one directory per run: the workspaces never collide.
    assert len({learning, twin, again}) == 3


def test_an_experiment_without_knowledge_keeps_the_default_naming() -> None:
    experiment = load_experiment_file(
        REPO_ROOT / "configs" / "experiments" / "knowledge-on-off.yaml"
    )
    assert _pin(experiment, "wordcount-001@1.0.0") is None


def test_the_shipped_atlas_memory_experiment_plans(dataset, plugin) -> None:
    experiment = load_experiment_file(ATLAS)
    builder = MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle="managed")
    plan = builder.plan(experiment)

    assert plan.ok, plan.validation.as_dict()
    assert len(plan.learning) == 1
    # Four scenarios, each a replay and its fresh control.
    assert [arm.mode for arm in plan.arms] == [KnowledgeMode.REPLAY, KnowledgeMode.FRESH] * 4
    replayed = {arm.task_uid for arm in plan.arms if arm.mode is KnowledgeMode.REPLAY}
    assert "atlas-drift-002@1.0.0" in replayed and "atlas-lineage-001@1.0.0" not in replayed

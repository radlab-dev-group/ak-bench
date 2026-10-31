"""Memory experiments (plan section 17): the comparison must hold equal.

The tests guard the rules that make a memory experiment a measurement: only
the knowledge access may differ between a replay and its fresh control, a
scenario must match its task, a replay must pass its readiness gate, and an
unconfirmed knowledge base is not a ready one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from akbench.descriptors import PluginDescriptor
from akbench.experiments import load_experiment_file
from akbench.experiments.descriptor import ExperimentDescriptor
from akbench.experiments.loader import LoadedExperiment
from akbench.knowledge.fingerprint import (
    MEMORY_INVARIANTS,
    fingerprint,
    invariant_differences,
)
from akbench.knowledge.isolation import build_isolation_report, namespace_isolation
from akbench.knowledge.modes import KnowledgeMode
from akbench.knowledge.planning import MemoryPlanBuilder, learning_session_id
from akbench.knowledge.readiness import (
    KbReadiness,
    NoReadbackProbe,
    ReadinessStatus,
    build_readiness_gate,
)
from akbench.knowledge.sessions import LearningSession, SessionTask

REPO_ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------- fingerprint


def test_a_fingerprint_is_stable_and_changes_with_a_fact() -> None:
    first = fingerprint({"repository": "repo", "commit": "abc"})
    again = fingerprint({"commit": "abc", "repository": "repo"})
    changed = fingerprint({"repository": "repo", "commit": "def"})

    assert first.digest == again.digest
    assert first.digest != changed.digest
    assert "repository" in first.facts


def test_invariant_comparison_names_the_key_that_differs() -> None:
    left = {"repository": "repo", "commit": "abc", "evaluator": "pytest_evaluator"}
    right = {"repository": "repo", "commit": "def", "evaluator": "pytest_evaluator"}

    assert invariant_differences(left, right) == ["commit"]


def test_a_fact_present_on_one_side_only_is_a_difference() -> None:
    assert invariant_differences({"model": "gpt"}, {}, keys=("model",)) == ["model"]


def test_the_invariants_exclude_the_knowledge_access() -> None:
    assert "knowledge" not in MEMORY_INVARIANTS
    assert "repository" in MEMORY_INVARIANTS


# -------------------------------------------------------------------- readiness


def _session(with_tasks: bool = True) -> LearningSession:
    tasks = [SessionTask("wordcount-001@1.0.0", "sha256:abc")] if with_tasks else []
    return LearningSession(
        session_id="ls",
        experiment_uid="exp/1.0.0",
        plugin_id="agentic_knowledge",
        plugin_version="1.0.0",
        tasks=tasks,
    )


def test_an_empty_learning_session_blocks_a_replay() -> None:
    gate = build_readiness_gate(_session(with_tasks=False), NoReadbackProbe())
    assert gate.blocked and not gate.allowed
    assert "no knowledge" in (gate.reason or "")


def test_the_default_probe_reports_unsupported_and_blocks() -> None:
    gate = build_readiness_gate(_session(), NoReadbackProbe())
    assert gate.blocked
    assert gate.readiness.status is ReadinessStatus.UNSUPPORTED
    assert gate.evidence_grade == "not_run"


def test_allowing_unverified_releases_the_gate_and_marks_it() -> None:
    gate = build_readiness_gate(_session(), NoReadbackProbe(), allow_unverified=True)
    assert gate.allowed
    assert gate.allow_unverified
    assert gate.evidence_grade == "unverified"


@dataclass(frozen=True)
class _ReadyProbe:
    probe_id: str = "readback"

    def check(self, session: LearningSession) -> KbReadiness:
        return KbReadiness(
            status=ReadinessStatus.READY,
            probe_id=self.probe_id,
            writes_settled=True,
            indexing_settled=True,
            evidence="kb worker reported the collection indexed",
        )


def test_a_confirmed_ready_knowledge_base_passes_the_gate() -> None:
    gate = build_readiness_gate(_session(), _ReadyProbe())
    assert gate.allowed
    assert gate.evidence_grade == "verified"
    assert gate.readiness.confirmed


def test_a_not_ready_knowledge_base_still_blocks() -> None:
    @dataclass(frozen=True)
    class _SlowProbe:
        probe_id: str = "readback"

        def check(self, session: LearningSession) -> KbReadiness:
            return KbReadiness(
                status=ReadinessStatus.NOT_READY,
                probe_id=self.probe_id,
                writes_settled=True,
                indexing_settled=False,
            )

    gate = build_readiness_gate(_session(), _SlowProbe())
    assert gate.blocked
    assert "not_ready" in (gate.reason or "")


# ----------------------------------------------------------------- isolation


def _plugin(**benchmark: Any) -> PluginDescriptor:
    body: dict[str, Any] = {
        "schema_version": "1.0",
        "id": "agentic_knowledge",
        "version": "1.0.0",
        "plugin": {"provider": "llm-router", "type": "knowledge"},
        "benchmark": {
            "observed_env": [
                {
                    "name": "LLM_ROUTER_KNOWLEDGE_AGENTIC_COLLECTION_PREFIX",
                    "type": "string",
                    "observed": True,
                    "controllable": False,
                }
            ]
        },
    }
    body["benchmark"] = {**body["benchmark"], **benchmark}
    return PluginDescriptor.model_validate(body)


def test_a_shared_router_cannot_isolate_the_namespace() -> None:
    level, reason = namespace_isolation(_plugin(), "external")
    assert level.value == "unsupported"
    assert "share one knowledge namespace" in (reason or "")


def test_a_managed_instance_can_scope_the_namespace() -> None:
    level, reason = namespace_isolation(_plugin(), "managed")
    assert level.value == "supported"
    assert "managed" in (reason or "")


def test_a_plugin_without_a_namespace_variable_cannot_be_isolated() -> None:
    level, _ = namespace_isolation(_plugin(observed_env=[]), "managed")
    assert level.value == "unsupported"
    report = build_isolation_report(_plugin(observed_env=[]), "managed")
    assert report.comparable is False


# ---------------------------------------------------------------------- plan


@pytest.fixture
def dataset():
    from akbench.datasets import Dataset

    return Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)


@pytest.fixture
def plugin() -> PluginDescriptor:
    from akbench.descriptors import DescriptorKind, load_registry

    registry = load_registry(REPO_ROOT / "descriptors")
    return next(
        item.descriptor
        for item in registry.entries(DescriptorKind.PLUGIN)
        if item.descriptor.id == "agentic_knowledge"
    )


def _memory_experiment(**overrides: Any) -> ExperimentDescriptor:
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "id": "memory",
        "version": "1.0.0",
        "experiment": {
            "type": "knowledge_replay",
            "agent": {"id": "codex"},
            "knowledge": {
                "plugin": "agentic_knowledge",
                "learning": {"tasks": ["wordcount-001@1.0.0"]},
                "scenarios": [
                    {"id": "same", "type": "exact_replay", "task": "wordcount-001@1.0.0"}
                ],
            },
        },
    }
    base["experiment"]["knowledge"] = {
        **base["experiment"]["knowledge"],
        **overrides,
    }
    return ExperimentDescriptor.model_validate(base)


def _loaded(experiment: ExperimentDescriptor) -> LoadedExperiment:
    from akbench.descriptors.registry import compute_digest

    payload = experiment.model_dump(mode="json")
    return LoadedExperiment(
        descriptor=experiment,
        path=Path("<memory>"),
        digest=compute_digest(payload),
    )


def test_a_planned_replay_and_fresh_share_one_fingerprint(dataset, plugin) -> None:
    plan = MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle="managed").plan(
        _loaded(_memory_experiment())
    )

    assert plan.ok
    assert [arm.mode for arm in plan.arms] == [
        KnowledgeMode.REPLAY,
        KnowledgeMode.FRESH,
    ]
    replay, fresh = plan.arms
    assert replay.fingerprint.digest == fresh.fingerprint.digest
    assert replay.knowledge_access == {"read": True, "write": False}
    assert fresh.knowledge_access == {"read": False, "write": False}
    assert replay.gate is not None and fresh.gate is None
    assert replay.depends_on == plan.learning_session.session_id


def test_the_learning_arm_is_the_only_one_that_writes(dataset, plugin) -> None:
    plan = MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle="managed").plan(
        _loaded(_memory_experiment())
    )
    for arm in list(plan.learning) + list(plan.arms):
        if arm.mode is KnowledgeMode.LEARNING:
            assert arm.knowledge_access["write"] is True
        else:
            assert arm.knowledge_access["write"] is False


def test_an_exact_replay_outside_the_learning_set_is_rejected(dataset, plugin) -> None:
    experiment = _memory_experiment(
        scenarios=[{"id": "same", "type": "exact_replay", "task": "ghost@1.0.0"}]
    )
    builder = MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle="managed")
    report = builder.validate(_loaded(experiment))
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "task_missing" in codes


def test_a_transfer_must_not_be_a_learning_task(dataset, plugin) -> None:
    experiment = _memory_experiment(
        scenarios=[
            {"id": "same", "type": "exact_replay", "task": "wordcount-001@1.0.0"},
            {"id": "again", "type": "related_transfer", "task": "wordcount-001@1.0.0"},
        ]
    )
    builder = MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle="managed")
    report = builder.validate(_loaded(experiment))
    assert not report.ok
    assert "transfer_task_in_learning" in {issue.code for issue in report.errors}


def test_a_learning_run_must_write(dataset, plugin) -> None:
    experiment = _memory_experiment(
        learning={"tasks": ["wordcount-001@1.0.0"], "write_enabled": False}
    )
    builder = MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle="managed")
    report = builder.validate(_loaded(experiment))
    assert not report.ok
    assert "learning_writes_disabled" in {issue.code for issue in report.errors}


def test_the_gate_is_blocked_without_a_probe_and_released_with_allow(dataset, plugin) -> None:
    builder = MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle="managed")
    experiment = _loaded(_memory_experiment())

    blocked = builder.plan(experiment)
    assert blocked.arms[0].gate is not None
    assert blocked.arms[0].gate.blocked
    assert blocked.arms[0].gate.evidence_grade == "not_run"

    released = builder.plan(experiment, allow_unverified=True)
    assert released.arms[0].gate is not None
    assert released.arms[0].gate.allowed
    assert released.arms[0].gate.evidence_grade == "unverified"


def test_a_confirmed_probe_allows_the_replay(dataset, plugin) -> None:
    builder = MemoryPlanBuilder(
        dataset=dataset, plugin=plugin, lifecycle="managed", readiness_probe=_ReadyProbe()
    )
    plan = builder.plan(_loaded(_memory_experiment()))
    assert plan.arms[0].gate is not None
    assert plan.arms[0].gate.allowed
    assert plan.arms[0].gate.evidence_grade == "verified"


def test_a_shared_namespace_warns_on_the_plan(dataset, plugin) -> None:
    builder = MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle="external")
    report = builder.validate(_loaded(_memory_experiment()))
    assert "knowledge_namespace_shared" in {
        issue.code for issue in report.issues if issue.severity.value == "warning"
    }


def test_the_shipped_example_plans(dataset, plugin) -> None:
    experiment = load_experiment_file(
        REPO_ROOT / "configs" / "experiments" / "knowledge-replay.yaml"
    )
    builder = MemoryPlanBuilder(dataset=dataset, plugin=plugin, lifecycle="managed")
    plan = builder.plan(experiment)

    assert plan.ok
    assert plan.plugin_id == "agentic_knowledge"
    assert len(plan.learning) == 1
    assert [arm.mode for arm in plan.arms] == [KnowledgeMode.REPLAY, KnowledgeMode.FRESH]


def test_a_learning_session_id_is_stable() -> None:
    first = learning_session_id("exp/1.0.0", "sha256:0123456789abcdef")
    again = learning_session_id("exp/1.0.0", "sha256:0123456789abcdef")
    different = learning_session_id("exp/2.0.0", "sha256:0123456789abcdef")
    assert first == again
    assert first != different
    assert first.startswith("learn-")


def test_learning_sessions_round_trip() -> None:
    session = _session()
    clone = LearningSession.from_dict(session.as_dict())
    assert clone.digest == session.digest
    assert clone.task_uids == session.task_uids

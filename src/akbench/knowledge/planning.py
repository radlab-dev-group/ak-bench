"""Planning a memory experiment (plan section 17).

The builder turns a ``knowledge_replay`` experiment descriptor into an
executable memory plan: a learning arm, one replay and one fresh arm per
scenario, the readiness gate each replay must pass, and the fingerprints that
prove every replay/fresh pair differs in knowledge access and in nothing else.

The plan does not run anything. It is the stage where the experiment either
becomes honest or fails: a scenario whose task is not in the dataset, a replay
whose knowledge base can never be confirmed, a pair of arms that differ in
more than the knowledge they see — each is a finding, and each finding names
what it found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from akbench.datasets import Dataset, TaskLoadError
from akbench.descriptors.plugin import PluginDescriptor
from akbench.experiments.descriptor import (
    ExperimentDescriptor,
    KnowledgeSelection,
)
from akbench.experiments.errors import ExperimentValidationError
from akbench.experiments.loader import LoadedExperiment
from akbench.experiments.validation import ValidationReport
from akbench.knowledge.fingerprint import (
    MEMORY_INVARIANTS,
    Fingerprint,
    invariant_fingerprint,
)
from akbench.knowledge.isolation import IsolationReport, build_isolation_report
from akbench.knowledge.modes import KnowledgeMode, ScenarioSpec, TransferScenario
from akbench.knowledge.readiness import KbReadinessProbe, ReplayGate, build_readiness_gate
from akbench.knowledge.sessions import LearningSession, SessionTask


@dataclass(frozen=True)
class MemoryArm:
    """One arm of the memory plan: what it runs and what it may see.

    ``knowledge_access`` is the manipulated factor — the only thing that may
    differ between a replay arm and the fresh arm of the same scenario.
    """

    arm_id: str
    mode: KnowledgeMode
    scenario: TransferScenario | None
    task_uid: str
    task_digest: str
    knowledge_access: dict[str, bool]
    fingerprint: Fingerprint
    position: int
    depends_on: str | None = None
    gate: ReplayGate | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "arm_id": self.arm_id,
            "mode": self.mode.value,
            "scenario": self.scenario.value if self.scenario else None,
            "task_uid": self.task_uid,
            "task_digest": self.task_digest,
            "knowledge_access": dict(self.knowledge_access),
            "fingerprint": self.fingerprint.as_dict(),
            "position": self.position,
            "depends_on": self.depends_on,
        }
        if self.gate is not None:
            payload["gate"] = self.gate.as_dict()
        return payload


@dataclass(frozen=True)
class MemoryExperimentPlan:
    """A memory experiment, expanded and ready to be scheduled."""

    experiment_uid: str
    experiment_digest: str
    plugin_id: str
    plugin_version: str
    learning: list[MemoryArm]
    arms: list[MemoryArm]
    learning_session: LearningSession
    isolation: IsolationReport
    scenarios: list[ScenarioSpec]
    validation: ValidationReport
    invariant_keys: tuple[str, ...] = MEMORY_INVARIANTS

    @property
    def ok(self) -> bool:
        return self.validation.ok

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment_uid,
            "experiment_digest": self.experiment_digest,
            "plugin": self.plugin_id,
            "plugin_version": self.plugin_version,
            "learning": [arm.as_dict() for arm in self.learning],
            "arms": [arm.as_dict() for arm in self.arms],
            "learning_session": self.learning_session.as_dict(),
            "isolation": self.isolation.as_dict(),
            "scenarios": [
                {"id": s.id, "type": s.type.value, "task": s.task} for s in self.scenarios
            ],
            "invariant_keys": list(self.invariant_keys),
            "validation": self.validation.as_dict(),
        }


class MemoryPlanBuilder:
    """Build and validate a memory experiment plan.

    ``readiness_probe`` is the evidence source for the replay gate. When it is
    ``None`` the default probe applies, and on a shared external router that
    means the gate will block unless the experiment explicitly allows an
    unverified knowledge base.
    """

    def __init__(
        self,
        *,
        dataset: Dataset,
        plugin: PluginDescriptor | None = None,
        lifecycle: str | None = None,
        readiness_probe: KbReadinessProbe | None = None,
    ) -> None:
        self.dataset = dataset
        self.plugin = plugin
        self.lifecycle = lifecycle
        self.readiness_probe = readiness_probe

    def plan(
        self,
        experiment: LoadedExperiment,
        allow_unverified: bool = False,
    ) -> MemoryExperimentPlan:
        """Build the plan; an invalid definition raises (plan 12.1).

        ``allow_unverified`` relaxes the replay gate for this invocation only:
        the experiment file is not modified, and the plan records the
        relaxation so a reader sees the replay was never confirmed.
        """
        report = self.validate(experiment)
        if not report.ok:
            codes = ", ".join(issue.code for issue in report.errors)
            raise ExperimentValidationError(
                f"memory experiment {experiment.identity} is not runnable: {codes}",
                details={"issues": [issue.as_dict() for issue in report.errors]},
            )
        return self._build(experiment, report, allow_unverified=allow_unverified)

    def validate(self, experiment: LoadedExperiment) -> ValidationReport:
        """Every check a memory experiment must pass, as findings."""
        report = ValidationReport()
        descriptor = experiment.descriptor
        knowledge = descriptor.experiment.knowledge
        if knowledge is None:
            report.error(
                "knowledge_block_missing",
                "the experiment has no knowledge block; a memory experiment needs "
                "the learning tasks, the replay gate and the scenarios",
            )
            return report

        self._check_plugin(descriptor, report)
        self._check_learning(knowledge, report)
        self._check_scenarios(knowledge, report)
        self._check_isolation(report)
        return report

    # ------------------------------------------------------------ components

    def _check_plugin(self, descriptor: ExperimentDescriptor, report: ValidationReport) -> None:
        knowledge = descriptor.experiment.knowledge
        if self.plugin is None:
            report.warning(
                "plugin_descriptor_missing",
                f"the plugin descriptor for {knowledge.plugin!r} is not loaded: the "
                "plan cannot check its namespace or its metrics",
            )
            return
        if self.plugin.id != knowledge.plugin:
            report.error(
                "plugin_mismatch",
                f"the experiment names plugin {knowledge.plugin!r} but the loaded "
                f"descriptor is {self.plugin.id!r}",
            )
        elif self.plugin.plugin.type != "knowledge":
            report.error(
                "plugin_not_knowledge",
                f"plugin {self.plugin.id!r} is of type {self.plugin.plugin.type!r}, "
                "not knowledge: a memory experiment measures the knowledge layer",
            )

    def _task(self, uid: str, report: ValidationReport) -> Any | None:
        try:
            return self.dataset.require(uid)
        except TaskLoadError as exc:
            report.error(
                "task_missing",
                f"the task {uid!r} is not in the dataset: {exc}",
                task=uid,
            )
            return None

    def _check_learning(
        self,
        knowledge: KnowledgeSelection,
        report: ValidationReport,
    ) -> None:
        for uid in knowledge.learning.tasks:
            self._task(uid, report)
        if knowledge.learning.write_enabled is False:
            report.error(
                "learning_writes_disabled",
                "the learning arm must have knowledge write enabled: a learning run "
                "that does not write is not a source of knowledge",
            )

    def _check_scenarios(
        self,
        knowledge: KnowledgeSelection,
        report: ValidationReport,
    ) -> None:
        learning_uids = set(knowledge.learning.tasks)
        seen_tasks: dict[str, str] = {}
        for scenario in knowledge.scenarios:
            loaded = self._task(scenario.task, report)
            if loaded is None:
                continue
            in_learning = scenario.task in learning_uids
            if scenario.type is TransferScenario.EXACT_REPLAY and not in_learning:
                report.error(
                    "exact_replay_not_in_learning",
                    f"scenario {scenario.id!r} is an exact replay of {scenario.task!r}, "
                    "which is not in the learning set: an exact replay must be a task "
                    "the learning arm actually worked",
                )
            if scenario.type is not TransferScenario.EXACT_REPLAY and in_learning:
                report.error(
                    "transfer_task_in_learning",
                    f"scenario {scenario.id!r} is a transfer to {scenario.task!r}, but "
                    "that task is in the learning set: a transfer must be a task the "
                    "learning arm did not work, or it is an exact replay",
                )
            if scenario.task in seen_tasks and seen_tasks[scenario.task] != scenario.type.value:
                report.error(
                    "conflicting_scenarios",
                    f"the task {scenario.task!r} is used for both a "
                    f"{seen_tasks[scenario.task]} and a {scenario.type.value} scenario: "
                    "a task has one relationship to the learned knowledge",
                )
            seen_tasks.setdefault(scenario.task, scenario.type.value)

    def _check_isolation(self, report: ValidationReport) -> None:
        isolation = build_isolation_report(self.plugin, self.lifecycle)
        if not isolation.comparable:
            report.warn(
                "knowledge_namespace_shared",
                "the knowledge namespace is not isolated on this deployment: every "
                "experiment on this router instance shares one knowledge base. The "
                "arms of this experiment remain distinguishable only because the "
                "fresh arm reads no knowledge, and two memory experiments on this "
                "instance will contaminate each other",
                reason=isolation.namespace_reason,
            )

    # ------------------------------------------------------------------ build

    def _build(
        self,
        experiment: LoadedExperiment,
        report: ValidationReport,
        allow_unverified: bool = False,
    ) -> MemoryExperimentPlan:
        descriptor = experiment.descriptor
        knowledge = descriptor.experiment.knowledge

        learning = self._load_learning(knowledge)
        session = LearningSession(
            session_id=learning_session_id(experiment.identity, experiment.digest),
            experiment_uid=experiment.identity,
            plugin_id=self.plugin.id if self.plugin else knowledge.plugin,
            plugin_version=self.plugin.version if self.plugin else "",
            tasks=[
                SessionTask(task_uid=loaded.uid, task_digest=loaded.digest)
                for loaded in learning
            ],
            collection_prefix_source="plugin default" if self.plugin is None else "descriptor",
        )
        gate = build_readiness_gate(
            session,
            self.readiness_probe,
            allow_unverified=allow_unverified or knowledge.replay.allow_unverified,
        )

        arms = self._build_arms(experiment, knowledge, gate, session, learning)
        return MemoryExperimentPlan(
            experiment_uid=experiment.identity,
            experiment_digest=experiment.digest,
            plugin_id=self.plugin.id if self.plugin else knowledge.plugin,
            plugin_version=self.plugin.version if self.plugin else "",
            learning=arms["learning"],
            arms=arms["arms"],
            learning_session=session,
            isolation=build_isolation_report(self.plugin, self.lifecycle),
            scenarios=list(knowledge.scenarios),
            validation=report,
        )

    def _load_learning(self, knowledge: KnowledgeSelection) -> list[Any]:
        loaded: list[Any] = []
        for uid in knowledge.learning.tasks:
            found = self.dataset.require(uid)
            loaded.append(found)
        return loaded

    def _arm_facts(
        self,
        experiment: LoadedExperiment,
        loaded: Any,
        model: str | None,
    ) -> dict[str, Any]:
        """The invariants of one arm: everything except the knowledge access."""
        body = experiment.descriptor.experiment
        repository = loaded.task.task.repository
        return {
            "repository": repository.source,
            "commit": repository.ref,
            "task": loaded.uid,
            "task_digest": loaded.digest,
            "evaluator": loaded.task.task.evaluator,
            "agent": f"{body.agent.id}@{body.agent.version or 'any'}",
            "agent_config": body.agent.config,
            "model": model,
            "limits": body.execution_policy.model_dump(mode="json"),
            "sandbox_image": body.execution.mode,
        }

    def _build_arms(
        self,
        experiment: LoadedExperiment,
        knowledge: Any,
        gate: ReplayGate,
        session: LearningSession,
        learning: list[Any],
    ) -> dict[str, list[MemoryArm]]:
        model = self._model_of(experiment)
        learning_arms: list[MemoryArm] = []
        for index, loaded in enumerate(learning):
            facts = self._arm_facts(experiment, loaded, model)
            learning_arms.append(
                MemoryArm(
                    arm_id=f"learning-{loaded.uid}",
                    mode=KnowledgeMode.LEARNING,
                    scenario=None,
                    task_uid=loaded.uid,
                    task_digest=loaded.digest,
                    knowledge_access={
                        "read": knowledge.learning.read_enabled,
                        "write": knowledge.learning.write_enabled,
                    },
                    fingerprint=invariant_fingerprint(facts),
                    position=index,
                )
            )

        arms: list[MemoryArm] = []
        for scenario in knowledge.scenarios:
            loaded = self.dataset.require(scenario.task)
            facts = self._arm_facts(experiment, loaded, model)
            base = {
                "task_uid": loaded.uid,
                "task_digest": loaded.digest,
                "fingerprint": invariant_fingerprint(facts),
                "depends_on": session.session_id,
            }
            arms.append(
                MemoryArm(
                    arm_id=f"replay-{scenario.id}",
                    mode=KnowledgeMode.REPLAY,
                    scenario=scenario.type,
                    knowledge_access={"read": True, "write": False},
                    gate=gate,
                    position=len(arms),
                    **base,
                )
            )
            arms.append(
                MemoryArm(
                    arm_id=f"fresh-{scenario.id}",
                    mode=KnowledgeMode.FRESH,
                    scenario=scenario.type,
                    knowledge_access={"read": False, "write": False},
                    position=len(arms),
                    **base,
                )
            )
        return {"learning": learning_arms, "arms": arms}

    def _model_of(self, experiment: LoadedExperiment) -> str | None:
        """The model the arms run on, if one is pinned in the experiment."""
        factors = experiment.descriptor.experiment.factors
        if "model" in factors.baseline:
            return str(factors.baseline["model"])
        return None


def learning_session_id(experiment_uid: str, experiment_digest: str) -> str:
    """A stable id for the learning session of one experiment.

    Derived from the experiment identity and its digest, so re-planning the
    same definition names the same session and a changed definition does not.
    """
    return f"learn-{experiment_uid}-{experiment_digest.removeprefix('sha256:')[:12]}"

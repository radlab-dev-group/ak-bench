"""Experiment planner (plan sections 12.1 to 12.3).

The planner turns a descriptor into an executable plan without running
anything: it validates the definition against the registries, selects the
tasks, expands the matrix into variants, and reports the cost. A plan can
therefore be reviewed, hashed and diffed before a single agent starts — which
is what makes an expensive experiment a deliberate decision rather than an
accident.

Three properties are enforced here rather than trusted:

- **nothing is assumed about the agent** — capabilities, controllable parameters
  and adapter availability come from descriptors (plan rules 9 and 25);
- **a factor is only a factor when the interface can set it** — plugin-level
  factors on a router that refuses per-run configuration are reported as
  requiring a managed instance, never silently treated as applied (rule 14);
- **a plan that exceeds its limits is an error** — the cost is computed before
  the first run, so a limit that is hit is a decision the author has to change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from akbench.datasets import Dataset
from akbench.descriptors import (
    AgentDescriptor,
    DescriptorKind,
    DescriptorRegistry,
    MetricDescriptor,
    RuntimeDescriptor,
)
from akbench.descriptors.registry import compute_digest
from akbench.descriptors.runtime import Lifecycle
from akbench.experiments.descriptor import ExperimentDescriptor, MatrixStrategy, RuntimeSelection
from akbench.experiments.dimensions import DimensionRegistry, Factor
from akbench.experiments.errors import ExperimentValidationError
from akbench.experiments.loader import LoadedExperiment
from akbench.experiments.strategies import Assignment, StrategyError, strategy_for
from akbench.experiments.validation import ValidationReport

AGENT_CONFIG_PREFIX = "agent.configuration."
AGENT_ID_SOURCE = "experiment.agent.id"
PLUGIN_SOURCE_PREFIX = "plugin."


@dataclass(frozen=True)
class PlanTask:
    """One selected task."""

    uid: str
    task_id: str
    version: str
    category: str
    difficulty: str
    digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "id": self.task_id,
            "version": self.version,
            "category": self.category,
            "difficulty": self.difficulty,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class PlanVariant:
    """One variant of the matrix: values, requested configuration and hashes.

    ``variant_id`` is derived from the requested configuration, so the same
    variant of the same experiment always has the same identity even when the
    matrix order changes.
    """

    variant_id: str
    index: int
    values: dict[str, Any]
    agent_id: str
    agent_config: dict[str, Any]
    environment_requests: dict[str, Any]
    config_hash: str
    is_baseline: bool
    applies: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "index": self.index,
            "values": dict(self.values),
            "agent_id": self.agent_id,
            "agent_config": dict(self.agent_config),
            "environment_requests": dict(self.environment_requests),
            "config_hash": self.config_hash,
            "is_baseline": self.is_baseline,
            "applies": dict(self.applies),
        }


@dataclass(frozen=True)
class PlanCounts:
    """The four numbers that decide what an experiment costs (plan 12.2)."""

    tasks: int
    variants: int
    repetitions: int
    runs: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "tasks": self.tasks,
            "variants": self.variants,
            "repetitions": self.repetitions,
            "runs": self.runs,
        }


@dataclass(frozen=True)
class PlanEstimate:
    """Cost of the plan, derived from declared timeouts only.

    An upper bound from the declared timeout is a fact about the configuration;
    a prediction of how long an agent will take is not, so no prediction is made.
    """

    run_seconds_upper_bound: int | None
    total_seconds_upper_bound: int | None
    basis: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_seconds_upper_bound": self.run_seconds_upper_bound,
            "total_seconds_upper_bound": self.total_seconds_upper_bound,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class ExperimentPlan:
    """A validated experiment, expanded and ready to run."""

    experiment: LoadedExperiment
    counts: PlanCounts
    tasks: list[PlanTask]
    variants: list[PlanVariant]
    factors: list[Factor]
    estimate: PlanEstimate
    validation: ValidationReport
    descriptor_snapshots: dict[str, str]
    agent_id: str
    mode: str
    runtime_id: str | None

    @property
    def ok(self) -> bool:
        return self.validation.ok

    def summary(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment.identity,
            "digest": self.experiment.digest,
            "type": self.experiment.descriptor.experiment.type.value,
            "agent": self.agent_id,
            "mode": self.mode,
            "runtime": self.runtime_id,
            "strategy": self.experiment.descriptor.experiment.factors.strategy.value,
            "counts": self.counts.as_dict(),
            "estimate": self.estimate.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "tasks": [task.as_dict() for task in self.tasks],
            "factors": [factor.as_dict() for factor in self.factors],
            "variants": [variant.as_dict() for variant in self.variants],
            "descriptor_snapshots": dict(self.descriptor_snapshots),
            "validation": self.validation.as_dict(),
        }


class ExperimentPlanner:
    """Validate an experiment descriptor and expand it into a plan."""

    def __init__(
        self,
        *,
        descriptors: DescriptorRegistry,
        dataset: Dataset,
        datasets_dir: Path | None = None,
        implemented_evaluators: set[str] | None = None,
    ) -> None:
        self.descriptors = descriptors
        self.dataset = dataset
        self.datasets_dir = datasets_dir
        self.implemented_evaluators = implemented_evaluators or set()
        self.dimensions = DimensionRegistry(descriptors)

    def validate(self, experiment: LoadedExperiment) -> ValidationReport:
        """Run every check of plan 12.1 and return the findings."""
        report = ValidationReport()
        descriptor = experiment.descriptor
        body = descriptor.experiment

        factors = self._check_factors(descriptor, report)
        self._check_agent(descriptor, factors, report)
        self._check_execution(descriptor, report)
        self._check_evaluation(descriptor, report)
        self._check_metrics(descriptor, report)

        tasks = self._select_tasks(descriptor, report)
        variants = self._build_variants(experiment, factors, report)
        self._check_baseline_coverage(descriptor, variants, report)

        counts = PlanCounts(
            tasks=len(tasks),
            variants=len(variants),
            repetitions=body.execution_policy.repetitions,
            runs=len(tasks) * len(variants) * body.execution_policy.repetitions,
        )
        self._check_limits(descriptor, counts, report)
        self._check_contradictions(descriptor, factors, report)
        return report

    def plan(self, experiment: LoadedExperiment) -> ExperimentPlan:
        """Produce the plan; an invalid descriptor raises (plan 12.1)."""
        report = self.validate(experiment)
        if not report.ok:
            codes = ", ".join(issue.code for issue in report.errors)
            raise ExperimentValidationError(
                f"experiment {experiment.identity} is not runnable: {codes}",
                details={"issues": [issue.as_dict() for issue in report.errors]},
            )

        descriptor = experiment.descriptor
        body = descriptor.experiment
        factors = self._factors_or_raise(descriptor)
        tasks = self._select_tasks(descriptor, ValidationReport())
        variants = self._build_variants(experiment, factors, ValidationReport())
        counts = PlanCounts(
            tasks=len(tasks),
            variants=len(variants),
            repetitions=body.execution_policy.repetitions,
            runs=len(tasks) * len(variants) * body.execution_policy.repetitions,
        )
        return ExperimentPlan(
            experiment=experiment,
            counts=counts,
            tasks=tasks,
            variants=variants,
            factors=factors,
            estimate=_estimate(counts, body.execution_policy.timeout_seconds),
            validation=report,
            descriptor_snapshots=self._snapshots(descriptor, factors),
            agent_id=body.agent.id,
            mode=body.execution.mode,
            runtime_id=body.execution.runtime.id if body.execution.runtime else None,
        )

    # ------------------------------------------------------------ components

    def _check_factors(
        self, descriptor: ExperimentDescriptor, report: ValidationReport
    ) -> list[Factor]:
        try:
            return self._factors_or_raise(descriptor)
        except Exception as exc:
            report.error("factor_unusable", str(exc))
            return []

    def _factors_or_raise(self, descriptor: ExperimentDescriptor) -> list[Factor]:
        return [
            self.dimensions.factor(reference.id, reference.values)
            for reference in descriptor.experiment.factors.dimensions
        ]

    def _check_agent(
        self,
        descriptor: ExperimentDescriptor,
        factors: list[Factor],
        report: ValidationReport,
    ) -> None:
        body = descriptor.experiment
        entry = self.descriptors.get(DescriptorKind.AGENT, body.agent.id, body.agent.version)
        if entry is None:
            known = ", ".join(
                sorted(
                    {
                        loaded.snapshot.id
                        for loaded in self.descriptors.entries(DescriptorKind.AGENT)
                    }
                )
            )
            report.error(
                "agent_unknown",
                f"agent {body.agent.id!r} is not described; known agents: {known or 'none'}",
            )
            return
        agent = entry.descriptor
        if not isinstance(agent, AgentDescriptor):  # pragma: no cover - registry guarantees
            return

        missing = agent.missing_capabilities(body.required_capabilities)
        if missing:
            report.error(
                "capability_unavailable",
                f"agent {agent.id} cannot provide: {', '.join(missing)}. "
                "Required capabilities must be verified or partial in the agent descriptor.",
            )

        declared = agent.agent.configuration_schema
        for name, value in body.agent.config.items():
            parameter = declared.get(name)
            if parameter is None:
                report.error(
                    "agent_parameter_unknown",
                    f"agent {agent.id} declares no configuration parameter {name!r}",
                )
                continue
            if not parameter.controllable:
                report.error(
                    "agent_parameter_uncontrollable",
                    f"agent {agent.id} parameter {name!r} is not controllable by experiments",
                )
            if parameter.allowed is not None and value not in parameter.allowed:
                report.error(
                    "agent_parameter_value",
                    f"agent {agent.id} parameter {name!r} value {value!r} is not in "
                    f"the allowed set {parameter.allowed}",
                )

        for factor in factors:
            parameter_name = _agent_parameter(factor)
            if parameter_name is None:
                continue
            parameter = declared.get(parameter_name)
            if parameter is None or not parameter.controllable:
                report.error(
                    "factor_not_agent_parameter",
                    f"factor {factor.id!r} maps to agent parameter {parameter_name!r}, "
                    f"which agent {agent.id} does not declare controllable",
                )
                continue
            if parameter.allowed is not None:
                outside = [value for value in factor.values if value not in parameter.allowed]
                if outside:
                    report.error(
                        "factor_value_not_agent_allowed",
                        f"factor {factor.id!r} values {outside} are not in agent "
                        f"{agent.id} allowed set {parameter.allowed}",
                    )

    def _check_execution(self, descriptor: ExperimentDescriptor, report: ValidationReport) -> None:
        body = descriptor.experiment
        mode = body.execution.mode
        selection = body.execution.runtime

        plugin_factors = [
            reference.id
            for reference in body.factors.dimensions
            if _is_plugin_source(self.descriptors, reference.id)
        ]
        if mode == "direct" and plugin_factors:
            report.error(
                "plugin_factor_without_runtime",
                f"factors {', '.join(plugin_factors)} are configured on a runtime, but "
                "the experiment runs in direct mode: nothing hosts those plugins",
            )
        if mode == "direct":
            return
        if selection is None:
            report.error(
                "runtime_required",
                f"execution mode {mode!r} requires execution.runtime; direct mode does not",
            )
            return
        entry = self.descriptors.get(DescriptorKind.RUNTIME, selection.id)
        if entry is None:
            known = ", ".join(
                sorted(
                    {
                        loaded.snapshot.id
                        for loaded in self.descriptors.entries(DescriptorKind.RUNTIME)
                    }
                )
            )
            report.error(
                "runtime_unknown",
                f"runtime {selection.id!r} is not described; known runtimes: {known or 'none'}",
            )
            return
        runtime = entry.descriptor
        if isinstance(runtime, RuntimeDescriptor):
            if not runtime.supports_mode(mode):
                report.error(
                    "runtime_mode_unsupported",
                    f"runtime {runtime.id} does not support mode {mode!r}; it declares "
                    f"{[m.value for m in runtime.runtime.execution_modes]}",
                )
            if selection.lifecycle and not runtime.supports_lifecycle(selection.lifecycle):
                report.error(
                    "runtime_lifecycle_unsupported",
                    f"runtime {runtime.id} does not support lifecycle "
                    f"{selection.lifecycle!r}; it declares "
                    f"[{', '.join(item.value for item in runtime.runtime.supported_lifecycles)}]",
                )
            if plugin_factors and not runtime.runtime.capabilities.per_run_plugin_control.usable:
                self._check_plugin_control(runtime, selection, plugin_factors, report)

    def _check_plugin_control(
        self,
        runtime: RuntimeDescriptor,
        selection: RuntimeSelection,
        plugin_factors: list[str],
        report: ValidationReport,
    ) -> None:
        """Plugin factors need an instance whose configuration this run owns.

        A managed instance is started by AK-Bench with the declared environment,
        so the value is applied by construction. An external instance is shared,
        its configuration read is refused, and changing it would change the
        experiment for everybody (plan 13) — so a factor that cannot be pinned
        or verified is rejected rather than assumed.
        """
        if selection.lifecycle == Lifecycle.MANAGED.value:
            report.warn(
                "plugin_factor_verified_by_construction",
                f"factors {', '.join(plugin_factors)} are applied to a managed "
                f"{runtime.id} at start; the run records them as requested, and "
                "verification still needs the plugin's own signal",
            )
            return
        report.error(
            "per_run_plugin_control_unsupported",
            f"runtime {runtime.id} cannot configure plugins per run "
            f"({runtime.runtime.capabilities.per_run_plugin_control.value}); factors "
            f"{', '.join(plugin_factors)} need execution.runtime.lifecycle set to "
            f"{Lifecycle.MANAGED.value!r} so their configuration belongs to this experiment",
        )

    def _check_evaluation(self, descriptor: ExperimentDescriptor, report: ValidationReport) -> None:
        for evaluator_id in descriptor.experiment.evaluation.evaluators:
            entry = self.descriptors.get(DescriptorKind.EVALUATOR, evaluator_id)
            if entry is None:
                report.error(
                    "evaluator_undeclared", f"evaluator {evaluator_id!r} has no descriptor"
                )
                continue
            if self.implemented_evaluators and evaluator_id not in self.implemented_evaluators:
                report.error(
                    "evaluator_not_implemented",
                    f"evaluator {evaluator_id!r} is described but not implemented here; "
                    f"implemented: {', '.join(sorted(self.implemented_evaluators))}",
                )

    def _check_metrics(self, descriptor: ExperimentDescriptor, report: ValidationReport) -> None:
        for metric_id in descriptor.experiment.metrics:
            entry = self.descriptors.get(DescriptorKind.METRIC, metric_id)
            if entry is None:
                report.error("metric_undeclared", f"metric {metric_id!r} has no descriptor")
                continue
            metric = entry.descriptor
            if isinstance(metric, MetricDescriptor) and not metric.computable:
                reason = metric.metric.unavailable_reason or "no source declared"
                report.warn(
                    "metric_unavailable",
                    f"metric {metric_id!r} cannot be computed ({reason}); it stays reported "
                    "as unavailable rather than as a zero",
                )

    def _check_limits(
        self, descriptor: ExperimentDescriptor, counts: PlanCounts, report: ValidationReport
    ) -> None:
        limits = descriptor.experiment.limits
        if limits is None:
            return
        if limits.max_variants is not None and counts.variants > limits.max_variants:
            report.error(
                "limit_variants",
                f"the plan expands to {counts.variants} variants, above the declared "
                f"limit of {limits.max_variants}",
            )
        if limits.max_tasks is not None and counts.tasks > limits.max_tasks:
            report.error(
                "limit_tasks",
                f"the plan selects {counts.tasks} tasks, above the declared limit of "
                f"{limits.max_tasks}",
            )
        if limits.max_runs is not None and counts.runs > limits.max_runs:
            report.error(
                "limit_runs",
                f"the plan requires {counts.runs} runs, above the declared limit of "
                f"{limits.max_runs}",
            )

    def _check_contradictions(
        self,
        descriptor: ExperimentDescriptor,
        factors: list[Factor],
        report: ValidationReport,
    ) -> None:
        body = descriptor.experiment
        factor_ids = {factor.id for factor in factors}

        overlap = sorted(set(body.agent.config) & {
            name for factor in factors if (name := _agent_parameter(factor)) is not None
        })
        if overlap:
            report.error(
                "factor_config_conflict",
                f"agent.config sets {', '.join(overlap)} while a factor varies the same "
                "parameter; the factor owns it, the static value must go",
            )

        experiment_type = body.type
        if experiment_type.value == "agent_comparison" and "agent" not in factor_ids:
            report.error(
                "comparison_without_factor",
                "type agent_comparison requires the 'agent' factor to vary",
            )
        if experiment_type.value == "model_comparison" and "model" not in factor_ids:
            report.error(
                "comparison_without_factor",
                "type model_comparison requires the 'model' factor to vary",
            )
        if body.execution_policy.timeout_seconds is None:
            report.warn(
                "timeout_undeclared",
                "execution_policy.timeout_seconds is not set: a hung agent has no "
                "deadline and the plan's cost cannot be bounded",
            )

    # ------------------------------------------------------------- selection

    def _select_tasks(
        self, descriptor: ExperimentDescriptor, report: ValidationReport
    ) -> list[PlanTask]:
        selection = descriptor.experiment.dataset
        if selection.path and self.datasets_dir is not None:
            wanted = Path(selection.path)
            if not wanted.is_absolute():
                wanted = self.datasets_dir / wanted
            if not wanted.exists():
                report.error(
                    "dataset_path_missing",
                    f"dataset.path {selection.path!r} does not exist under {self.datasets_dir}",
                )
                return []

        filters = selection.filters
        tasks: list[PlanTask] = []
        for loaded in self.dataset.tasks:
            task = loaded.task
            if filters.categories and task.category not in filters.categories:
                continue
            if filters.difficulties and task.difficulty not in filters.difficulties:
                continue
            if filters.task_ids and not any(
                task.id == wanted or task.uid == wanted for wanted in filters.task_ids
            ):
                continue
            tasks.append(
                PlanTask(
                    uid=task.uid,
                    task_id=task.id,
                    version=task.version,
                    category=task.category,
                    difficulty=task.difficulty,
                    digest=loaded.digest,
                )
            )
        if not tasks:
            report.error(
                "dataset_selection_empty",
                "the dataset filters select no task; an experiment with zero tasks "
                "produces zero evidence",
                context={
                    "categories": filters.categories,
                    "difficulties": filters.difficulties,
                    "task_ids": filters.task_ids,
                },
            )
        return tasks

    # ------------------------------------------------------------- variants

    def _build_variants(
        self,
        experiment: LoadedExperiment,
        factors: list[Factor],
        report: ValidationReport,
    ) -> list[PlanVariant]:
        descriptor = experiment.descriptor
        descriptor_digest = experiment.digest
        body = descriptor.experiment
        factors_block = body.factors
        try:
            assignments = self._expand(factors_block, factors)
        except StrategyError as exc:
            report.error(exc.code, str(exc))
            return []

        baseline = dict(factors_block.baseline)
        variants: list[PlanVariant] = []
        for index, assignment in enumerate(assignments):
            agent_id, agent_config, environment, applies = self._requested_config(
                descriptor, factors, assignment
            )
            config_hash = _config_hash(
                source_digest=descriptor_digest,
                agent_id=agent_id,
                mode=body.execution.mode,
                runtime_id=body.execution.runtime.id if body.execution.runtime else None,
                agent_config=agent_config,
                environment=environment,
            )
            variant_id = "v-" + hashlib.sha256(
                json.dumps(
                    {"experiment": descriptor_digest, "config": config_hash},
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()[:12]
            variants.append(
                PlanVariant(
                    variant_id=variant_id,
                    index=index,
                    values=dict(assignment),
                    agent_id=agent_id,
                    agent_config=agent_config,
                    environment_requests=environment,
                    config_hash=config_hash,
                    is_baseline=_matches_baseline(assignment, baseline),
                    applies=applies,
                )
            )
        return variants

    def _requested_config(
        self,
        descriptor: ExperimentDescriptor,
        factors: list[Factor],
        assignment: Assignment,
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, str]]:
        """Translate factor values into the configuration they ask for.

        A value only becomes an agent parameter when the dimension says it is
        configured through the agent's own configuration; anything else is
        recorded as an environment request together with the declared way of
        configuring it, so the plan states how it is supposed to be applied and
        nobody has to guess.
        """
        body = descriptor.experiment
        agent_id = body.agent.id
        agent_config: dict[str, Any] = dict(body.agent.config)
        environment: dict[str, Any] = {}
        applies: dict[str, str] = {}

        for factor in factors:
            value = assignment[factor.id]
            parameter = _agent_parameter(factor)
            source = factor.descriptor.dimension.source or ""
            if source == AGENT_ID_SOURCE:
                agent_id = str(value)
                applies[factor.id] = "agent id"
            elif parameter is not None:
                agent_config[parameter] = value
                applies[factor.id] = f"agent parameter {parameter!r}"
            elif source.startswith(PLUGIN_SOURCE_PREFIX):
                environment[factor.id] = value
                applies[factor.id] = factor.configure_via or "plugin configuration"
            else:
                environment[factor.id] = value
                applies[factor.id] = factor.configure_via or "declared but unmapped"
        return agent_id, agent_config, environment, applies

    def _check_baseline_coverage(
        self,
        descriptor: ExperimentDescriptor,
        variants: list[PlanVariant],
        report: ValidationReport,
    ) -> None:
        baseline = descriptor.experiment.factors.baseline
        if baseline and not any(variant.is_baseline for variant in variants):
            report.error(
                "baseline_not_in_matrix",
                "the declared baseline does not appear among the generated variants, "
                "so the comparison would have no reference",
                context={"baseline": dict(baseline)},
            )
        if not baseline:
            report.warn(
                "baseline_undeclared",
                "no baseline is declared: differences between variants will have no "
                "reference point in the report",
            )

    # ------------------------------------------------------------ snapshots

    def _snapshots(
        self, descriptor: ExperimentDescriptor, factors: list[Factor]
    ) -> dict[str, str]:
        """Pin every descriptor the plan depends on (plan section 9)."""
        body = descriptor.experiment
        wanted: list[tuple[DescriptorKind, str]] = [
            (DescriptorKind.AGENT, body.agent.id),
        ]
        if body.execution.runtime:
            wanted.append((DescriptorKind.RUNTIME, body.execution.runtime.id))
        for reference in body.factors.dimensions:
            wanted.append((DescriptorKind.DIMENSION, reference.id))
        for evaluator_id in body.evaluation.evaluators:
            wanted.append((DescriptorKind.EVALUATOR, evaluator_id))
        for metric_id in body.metrics:
            wanted.append((DescriptorKind.METRIC, metric_id))

        snapshots: dict[str, str] = {}
        for kind, item_id in wanted:
            entry = self.descriptors.get(kind, item_id)
            if entry is not None:
                snapshots[entry.identity] = entry.snapshot.digest
        return snapshots

    def _expand(self, factors_block: Any, factors: list[Factor]) -> list[Assignment]:
        """Call the strategy, passing combinations only to the one that takes them."""
        strategy = strategy_for(factors_block.strategy.value)
        baseline = dict(factors_block.baseline)
        selected = [str(item) for item in factors_block.selected]
        if factors_block.strategy is MatrixStrategy.CUSTOM_MATRIX:
            combinations = [dict(item) for item in factors_block.combinations]
            return strategy(factors, baseline, selected, combinations=combinations)
        return strategy(factors, baseline, selected)


def _agent_parameter(factor: Factor) -> str | None:
    """The agent configuration parameter a factor drives, when it drives one."""
    source = factor.descriptor.dimension.source or ""
    if source.startswith(AGENT_CONFIG_PREFIX):
        return source[len(AGENT_CONFIG_PREFIX) :]
    return None


def _is_plugin_source(descriptors: DescriptorRegistry, dimension_id: str) -> bool:
    """True when a factor is configured through a plugin rather than the agent."""
    entry = descriptors.get(DescriptorKind.DIMENSION, dimension_id)
    if entry is None:
        return False
    source = getattr(entry.descriptor.dimension, "source", "") or ""
    return source.startswith(PLUGIN_SOURCE_PREFIX)




def _matches_baseline(assignment: Assignment, baseline: dict[str, Any]) -> bool:
    """The variant that carries the declared reference configuration."""
    if not baseline:
        return False
    for key, value in baseline.items():
        if type(assignment.get(key)) is not type(value) or assignment.get(key) != value:
            return False
    return True


def _config_hash(
    *,
    source_digest: str,
    agent_id: str,
    mode: str,
    runtime_id: str | None,
    agent_config: dict[str, Any],
    environment: dict[str, Any],
) -> str:
    """A hash of what the variant asks for, pinned to the experiment it came from."""
    payload = {
        "agent_id": agent_id,
        "mode": mode,
        "runtime_id": runtime_id,
        "agent_config": agent_config,
        "environment": environment,
        "source_digest": source_digest,
    }
    return compute_digest(payload)


def _estimate(counts: PlanCounts, timeout_seconds: int | None) -> PlanEstimate:
    if timeout_seconds is None:
        return PlanEstimate(
            run_seconds_upper_bound=None,
            total_seconds_upper_bound=None,
            basis="no timeout declared, so the cost cannot be bounded",
        )
    return PlanEstimate(
        run_seconds_upper_bound=timeout_seconds,
        total_seconds_upper_bound=timeout_seconds * counts.runs,
        basis="declared timeout_seconds multiplied by the number of runs (an upper bound)",
    )

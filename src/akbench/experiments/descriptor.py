"""Experiment descriptor (plan section 12).

An experiment is a versioned YAML file that names the agent under test, the
optional runtime, the dataset selection, the factors, the matrix strategy, the
repetitions, the isolation policy, the evaluators and the metrics.

The model is strict (``extra="forbid"``): a typo in an experiment file is a
mistake that must be reported, not a setting that is silently ignored while the
experiment runs something else than what the author meant.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from akbench.descriptors.base import DescriptorBase
from akbench.knowledge.modes import ScenarioSpec

RESERVED_FACTOR_IDS = frozenset({"repetition"})


class ExperimentType(StrEnum):
    """What the experiment varies (plan 12 and 25).

    Configuration experiments are kept apart from learning experiments on
    purpose: mixing them makes a memory effect indistinguishable from a
    configuration change (plan rule 16).
    """

    CONFIGURATION = "configuration"
    AGENT_COMPARISON = "agent_comparison"
    MODEL_COMPARISON = "model_comparison"
    KNOWLEDGE_REPLAY = "knowledge_replay"


class MatrixStrategy(StrEnum):
    FULL_FACTORIAL = "full_factorial"
    SELECTED_FACTORS = "selected_factors"
    ONE_FACTOR_AT_A_TIME = "one_factor_at_a_time"
    PAIRWISE = "pairwise"
    CUSTOM_MATRIX = "custom_matrix"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSelection(_StrictModel):
    """The agent under test and the configuration it is asked to use."""

    id: str = Field(..., min_length=1, max_length=128)
    version: str | None = None
    config: dict[str, object] = Field(default_factory=dict)


class RuntimeSelection(_StrictModel):
    id: str = Field(..., min_length=1, max_length=128)
    lifecycle: str | None = None


class ExecutionSelection(_StrictModel):
    mode: str = "direct"
    runtime: RuntimeSelection | None = None

    @model_validator(mode="after")
    def _check_mode(self) -> ExecutionSelection:
        if self.mode not in {"direct", "runtime", "router"}:
            raise ValueError("execution.mode must be one of direct, runtime, router")
        if self.runtime is not None and self.mode == "direct":
            raise ValueError(
                "execution.runtime is declared with mode 'direct'; name a runtime "
                "only in runtime or router mode"
            )
        return self


class DatasetFilters(_StrictModel):
    categories: list[str] = Field(default_factory=list)
    difficulties: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)


class DatasetSelection(_StrictModel):
    id: str | None = None
    version: str | None = None
    path: str | None = None
    filters: DatasetFilters = Field(default_factory=DatasetFilters)


class FactorReference(_StrictModel):
    """One factor: a dimension id, optionally narrowed to some of its values."""

    id: str = Field(..., min_length=1, max_length=128)
    values: list[object] | None = None

    @field_validator("values")
    @classmethod
    def _values_not_empty(cls, value: list[object] | None) -> list[object] | None:
        if value is not None and not value:
            raise ValueError("factor values must not be an empty list")
        return value


class Factors(_StrictModel):
    strategy: MatrixStrategy = MatrixStrategy.FULL_FACTORIAL
    dimensions: list[FactorReference] = Field(default_factory=list)
    selected: list[str] = Field(default_factory=list)
    baseline: dict[str, object] = Field(default_factory=dict)
    combinations: list[dict[str, object]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_factors(self) -> Factors:
        ids = [reference.id for reference in self.dimensions]
        duplicates = sorted({name for name in ids if ids.count(name) > 1})
        if duplicates:
            raise ValueError(f"factors declare duplicate dimensions: {', '.join(duplicates)}")
        reserved = sorted(set(ids) & RESERVED_FACTOR_IDS)
        if reserved:
            raise ValueError(
                f"{', '.join(reserved)} is not a factor: repetitions are governed by "
                "execution_policy.repetitions, not by a factor"
            )
        if self.strategy is MatrixStrategy.CUSTOM_MATRIX and not self.combinations:
            raise ValueError("strategy custom_matrix requires a non-empty combinations list")
        if self.strategy is not MatrixStrategy.CUSTOM_MATRIX and self.combinations:
            raise ValueError("combinations are only meaningful with strategy custom_matrix")
        if self.selected:
            unknown = sorted(set(self.selected) - set(ids))
            if unknown:
                raise ValueError(
                    f"factors.selected names dimensions that are not declared: "
                    f"{', '.join(unknown)}"
                )
        if self.strategy is MatrixStrategy.SELECTED_FACTORS and not self.selected:
            raise ValueError(
                "strategy selected_factors requires factors.selected: naming the "
                "dimensions that vary is the point of the strategy"
            )
        if self.strategy is not MatrixStrategy.SELECTED_FACTORS and self.selected:
            raise ValueError(
                "factors.selected is only meaningful with strategy selected_factors"
            )
        for key in self.baseline:
            if key not in ids:
                raise ValueError(
                    f"factors.baseline names {key!r}, which is not a declared factor"
                )
        return self


class ExecutionPolicy(_StrictModel):
    repetitions: int = Field(default=1, ge=1, le=1000)
    concurrency: int = Field(default=1, ge=1, le=64)
    timeout_seconds: int | None = Field(default=None, gt=0)
    evaluation_timeout_seconds: int | None = Field(default=None, gt=0)
    retry_infrastructure_errors: int = Field(default=0, ge=0, le=10)
    retry_agent_failures: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def _check_agent_retries(self) -> ExecutionPolicy:
        if self.retry_agent_failures:
            raise ValueError(
                "retry_agent_failures must be 0: retrying an agent failure measures "
                "the retry, not the agent (plan section 15)"
            )
        return self


class Isolation(_StrictModel):
    """Plan section 14: every run gets its own workspace and session."""

    workspace_per_run: bool = True
    fresh_agent_session: bool = True
    clean_agent_context: bool = True
    cleanup_workspace: bool = False

    @model_validator(mode="after")
    def _check_isolation(self) -> Isolation:
        if not self.workspace_per_run:
            raise ValueError(
                "isolation.workspace_per_run cannot be false: two runs in one "
                "workspace contaminate each other"
            )
        if self.clean_agent_context and not self.fresh_agent_session:
            raise ValueError(
                "clean_agent_context requires fresh_agent_session: a reused session "
                "carries the context of the previous run"
            )
        return self


class Evaluation(_StrictModel):
    evaluators: list[str] = Field(default_factory=list)
    baseline: str | None = None  # "base_state" | "none"

    @field_validator("baseline")
    @classmethod
    def _check_baseline(cls, value: str | None) -> str | None:
        if value is not None and value not in {"base_state", "none"}:
            raise ValueError("evaluation.baseline must be 'base_state' or 'none'")
        return value


class Limits(_StrictModel):
    """Plan 12.2: the planner applies configurable limits to the plan's cost."""

    max_runs: int | None = Field(default=None, ge=1)
    max_variants: int | None = Field(default=None, ge=1)
    max_tasks: int | None = Field(default=None, ge=1)


class Reporting(_StrictModel):
    generate_html: bool = False
    generate_json: bool = True
    generate_csv: bool = False


class LearningSelection(_StrictModel):
    """The learning arm of a memory experiment: which tasks write knowledge."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[str] = Field(default_factory=list, min_length=1)
    write_enabled: bool = True
    read_enabled: bool = True


class ReplaySelection(_StrictModel):
    """How the replay arm is gated before it starts (plan section 17)."""

    model_config = ConfigDict(extra="forbid")

    requires_readiness: bool = True
    # Explicit opt-in to start a replay without a confirmed knowledge base.
    # The run is then recorded as unverified (docs/KNOWLEDGE_REPLAY.md).
    allow_unverified: bool = False


class KnowledgeSelection(_StrictModel):
    """The knowledge block of a memory experiment (plan section 17).

    Only present when the experiment's type is ``knowledge_replay``.
    """

    model_config = ConfigDict(extra="forbid")

    plugin: str = Field("agentic_knowledge", min_length=1, max_length=128)
    learning: LearningSelection = Field(default_factory=LearningSelection)
    replay: ReplaySelection = Field(default_factory=ReplaySelection)
    # A memory experiment without a fresh control measures nothing: the fresh
    # arm is what separates "knowledge helped" from "the second try helped".
    fresh_control: bool = True
    scenarios: list[ScenarioSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_scenarios(self) -> KnowledgeSelection:
        if not self.scenarios:
            raise ValueError(
                "a knowledge_replay experiment needs at least one scenario: the "
                "relation between the tested task and the learned knowledge"
            )
        ids = [scenario.id for scenario in self.scenarios]
        duplicates = sorted({name for name in ids if ids.count(name) > 1})
        if duplicates:
            raise ValueError(
                f"knowledge.scenarios declare duplicate ids: {', '.join(duplicates)}"
            )
        if not self.fresh_control:
            raise ValueError(
                "knowledge.fresh_control cannot be false: without the fresh arm the "
                "replay result is not attributable to knowledge"
            )
        return self


class ExperimentBody(_StrictModel):
    type: ExperimentType = ExperimentType.CONFIGURATION
    agent: AgentSelection
    execution: ExecutionSelection = Field(default_factory=ExecutionSelection)
    dataset: DatasetSelection = Field(default_factory=DatasetSelection)
    factors: Factors = Field(default_factory=Factors)
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    isolation: Isolation = Field(default_factory=Isolation)
    evaluation: Evaluation = Field(default_factory=Evaluation)
    metrics: list[str] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    reporting: Reporting = Field(default_factory=Reporting)
    knowledge: KnowledgeSelection | None = None
    required_capabilities: list[str] = Field(default_factory=list)


class ExperimentDescriptor(DescriptorBase):
    """One experiment definition (plan section 12)."""

    experiment: ExperimentBody = Field(default_factory=ExperimentBody)

    @model_validator(mode="after")
    def _check_knowledge_block(self) -> ExperimentDescriptor:
        body = self.experiment
        if body.knowledge is not None and body.type is not ExperimentType.KNOWLEDGE_REPLAY:
            raise ValueError(
                "the knowledge block is only valid for experiments of type "
                "knowledge_replay"
            )
        if body.type is ExperimentType.KNOWLEDGE_REPLAY and body.knowledge is None:
            raise ValueError(
                "a knowledge_replay experiment needs a knowledge block: the "
                "learning tasks, the replay gate and the scenarios"
            )
        return self

    @property
    def agent_id(self) -> str:
        return self.experiment.agent.id

    @property
    def strategy(self) -> MatrixStrategy:
        return self.experiment.factors.strategy

    @property
    def repetitions(self) -> int:
        return self.experiment.execution_policy.repetitions

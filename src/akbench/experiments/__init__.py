"""Experiment descriptors, validation and planning (plan sections 11 and 12).

An experiment is defined in a versioned YAML file, validated against the
registries and expanded into a plan of variants, tasks and runs. Planning never
starts an agent: the plan is reviewed, hashed and costed first (plan 12.1).
"""

from akbench.experiments.descriptor import (
    DatasetFilters,
    DatasetSelection,
    ExecutionPolicy,
    ExperimentBody,
    ExperimentDescriptor,
    ExperimentType,
    FactorReference,
    Factors,
    Isolation,
    Limits,
    MatrixStrategy,
)
from akbench.experiments.dimensions import DimensionRegistry, DimensionResolutionError, Factor
from akbench.experiments.errors import ExperimentError, ExperimentValidationError
from akbench.experiments.loader import (
    LoadedExperiment,
    load_experiment_directory,
    load_experiment_file,
    parse_experiment,
)
from akbench.experiments.planner import (
    ExperimentPlan,
    ExperimentPlanner,
    PlanCounts,
    PlanEstimate,
    PlanTask,
    PlanVariant,
)
from akbench.experiments.strategies import StrategyError, strategy_for
from akbench.experiments.validation import IssueSeverity, ValidationIssue, ValidationReport

__all__ = [
    "DatasetFilters",
    "DatasetSelection",
    "DimensionRegistry",
    "DimensionResolutionError",
    "ExecutionPolicy",
    "ExperimentBody",
    "ExperimentDescriptor",
    "ExperimentError",
    "ExperimentPlan",
    "ExperimentPlanner",
    "ExperimentType",
    "ExperimentValidationError",
    "Factor",
    "FactorReference",
    "Factors",
    "Isolation",
    "IssueSeverity",
    "Limits",
    "LoadedExperiment",
    "MatrixStrategy",
    "PlanCounts",
    "PlanEstimate",
    "PlanTask",
    "PlanVariant",
    "StrategyError",
    "ValidationIssue",
    "ValidationReport",
    "load_experiment_directory",
    "load_experiment_file",
    "parse_experiment",
    "strategy_for",
]

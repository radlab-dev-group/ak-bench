"""Evaluator engine (plan section 16).

The evaluator judges the agent's result independently of anything the agent
declares. Hidden tests are never copied into the agent workspace: they run in an
isolated copy of the produced workspace, so the agent can neither read nor
modify them (plan 8.6, 23).

The outcome vocabulary distinguishes full success from partial success,
failure, regression, timeout, evaluator errors and infrastructure errors — an
evaluator problem is never recorded as an agent failure (plan rule 11).
"""

from akbench.evaluators.engine import (
    EvaluationResult,
    EvaluationVerdict,
    Evaluator,
    EvaluatorEngine,
)
from akbench.evaluators.registry import EvaluatorRegistry

__all__ = [
    "EvaluationResult",
    "EvaluationVerdict",
    "Evaluator",
    "EvaluatorEngine",
    "EvaluatorRegistry",
]

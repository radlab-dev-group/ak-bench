"""Evaluator descriptor (plan section 16).

The evaluator judges the result independently of anything the agent declares,
and hidden tests must run outside the agent workspace.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from akbench.descriptors.base import DescriptorBase


class EvaluatorKind(StrEnum):
    PYTEST = "pytest"
    COMMAND = "command"
    STATIC_ANALYSIS = "static_analysis"
    DIFF = "diff"
    PYTHON = "python"


class ResultKind(StrEnum):
    PASS_FAIL = "pass_fail"
    PARTIAL = "partial"
    SCORE = "score"


class EvaluatorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvaluatorKind
    # Hidden tests and evaluator code must stay out of the agent workspace.
    runs_outside_workspace: bool = True
    result_kind: ResultKind = ResultKind.PASS_FAIL
    command: str | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    notes: str | None = None


class EvaluatorDescriptor(DescriptorBase):
    """How a task result is judged."""

    evaluator: EvaluatorBody

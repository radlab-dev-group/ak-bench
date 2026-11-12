"""Task Descriptor (plan section 8.3).

A task is a versioned definition, not a directory listing: stable id, pinned
repository commit, category, difficulty, setup, mutation and evaluator. The
descriptor never embeds the hidden tests themselves — they are referenced by
path and must stay outside every agent workspace (plan 8.6).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from akbench.descriptors.base import DescriptorBase

DIFFICULTIES = ("easy", "medium", "hard", "expert")


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class RepositorySpec(BaseModel):
    """Where the task's code comes from and which state is pinned.

    ``source`` is a git URL or a local path. ``ref`` is the base commit (or a
    branch/tag that resolves to it); the resolved commit hash is recorded per
    run, because a branch name alone is not reproducible.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1)
    ref: str = Field(..., min_length=1)
    # Subdirectory inside the repository, when the task is not the whole repo.
    subdir: str | None = None
    # Public submodules or fixtures the agent may read.
    notes: str | None = None


class MutationSpec(BaseModel):
    """A controlled, versioned defect applied on top of the base commit (plan 8.4)."""

    model_config = ConfigDict(extra="forbid")

    patch: str = Field(..., min_length=1, description="Patch file relative to the task directory.")
    version: str = Field(..., min_length=1)
    # How the mutation was proven: hidden tests must fail once it is applied.
    verification: str = Field(default="hidden_tests", min_length=1)
    notes: str | None = None


class TaskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(..., min_length=1)
    difficulty: Difficulty
    repository: RepositorySpec
    mutation: MutationSpec | None = None
    # One evaluator id, or the list of them when a task is judged by more than
    # one measurement. The first entry is the primary: it is what a historical
    # row quotes when it can quote only one.
    evaluator: str | list[str] = Field(..., min_length=1, description="Evaluator descriptor id(s).")
    # Per-evaluator inputs, keyed by evaluator id: the ``command`` a command or
    # static-analysis evaluator runs, the ``script`` a python evaluator runs.
    # Keeping them here is what makes a verdict reproducible from the task.
    evaluator_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Directories inside the task kept away from the agent workspace.
    hidden_tests: str = Field(default="hidden_tests", min_length=1)
    public_tests: str | None = None
    setup: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(default=None, gt=0)
    constraints: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("evaluator", mode="after")
    @classmethod
    def _check_evaluator_entries(cls, value: str | list[str]) -> list[str]:
        entries = [value] if isinstance(value, str) else list(value)
        cleaned = [entry.strip() for entry in entries]
        if not cleaned or any(not entry for entry in cleaned):
            raise ValueError("an evaluator reference must not be empty")
        duplicates = sorted({entry for entry in cleaned if cleaned.count(entry) > 1})
        if duplicates:
            raise ValueError(f"an evaluator may be declared only once: {', '.join(duplicates)}")
        unknown = [entry for entry in cleaned if "@" in entry]
        if unknown:
            raise ValueError(
                "evaluator_inputs and the evaluator field take a bare id, not id@version: "
                + ", ".join(unknown)
            )
        return cleaned

    @field_validator("evaluator_inputs", mode="after")
    @classmethod
    def _check_evaluator_inputs_declared(cls, value: dict[str, dict[str, Any]]) -> dict[str, Any]:
        for key in value:
            if not key or not key.strip():
                raise ValueError("an evaluator_inputs key must be an evaluator id")
        return value

    @property
    def evaluators(self) -> list[str]:
        """Every evaluator id the task names, in the order it names them."""
        return list(self.evaluator)

    @property
    def primary_evaluator(self) -> str:
        """The evaluator a single-valued reader quotes: the first declared."""
        return self.evaluator[0]

    def inputs_for(self, evaluator_id: str) -> dict[str, Any]:
        """The inputs this task declares for one evaluator, and nothing else."""
        return dict(self.evaluator_inputs.get(evaluator_id, {}))

    @model_validator(mode="after")
    def _check_category_specific_requirements(self) -> TaskBody:
        # A bug fix is a bug fix only if a controlled defect exists (plan 8.4).
        if self.category == "bug_fix" and self.mutation is None:
            raise ValueError("a bug_fix task must declare a mutation patch")
        return self


class TaskDescriptor(DescriptorBase):
    """One benchmark task."""

    task: TaskBody

    @property
    def category(self) -> str:
        return self.task.category

    @property
    def difficulty(self) -> str:
        return self.task.difficulty.value

    @property
    def evaluator(self) -> str:
        """The primary evaluator id; a task may declare more than one."""
        return self.task.primary_evaluator

    @property
    def evaluators(self) -> list[str]:
        """Every evaluator id the task declares, primary first."""
        return self.task.evaluators

    @property
    def uid(self) -> str:
        """Stable cross-reference id used in the database and in run records."""
        return f"{self.id}@{self.version}"

    def requires_mutation(self) -> bool:
        return self.task.mutation is not None

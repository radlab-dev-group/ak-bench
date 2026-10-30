"""Task Descriptor (plan section 8.3).

A task is a versioned definition, not a directory listing: stable id, pinned
repository commit, category, difficulty, setup, mutation and evaluator. The
descriptor never embeds the hidden tests themselves — they are referenced by
path and must stay outside every agent workspace (plan 8.6).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    evaluator: str = Field(..., min_length=1, description="Evaluator descriptor id.")
    # Directories inside the task kept away from the agent workspace.
    hidden_tests: str = Field(default="hidden_tests", min_length=1)
    public_tests: str | None = None
    setup: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(default=None, gt=0)
    constraints: list[str] = Field(default_factory=list)
    notes: str | None = None

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
        return self.task.evaluator

    @property
    def uid(self) -> str:
        """Stable cross-reference id used in the database and in run records."""
        return f"{self.id}@{self.version}"

    def requires_mutation(self) -> bool:
        return self.task.mutation is not None

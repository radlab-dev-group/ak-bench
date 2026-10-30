"""Category descriptor (plan section 8.1).

Categories are registered, not a closed enum in the engine: adding a category
must not require engine changes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from akbench.descriptors.base import DescriptorBase

DIFFICULTIES = ("easy", "medium", "hard", "expert")


class CategoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    difficulties: list[str] = Field(default_factory=lambda: list(DIFFICULTIES))
    default_evaluators: list[str] = Field(default_factory=list)
    task_requirements: list[str] = Field(default_factory=list)
    notes: str | None = None


class CategoryDescriptor(DescriptorBase):
    """A task category registered through a descriptor."""

    category: CategoryBody = Field(default_factory=CategoryBody)

    def allows_difficulty(self, difficulty: str) -> bool:
        return self.category.enabled and difficulty in self.category.difficulties

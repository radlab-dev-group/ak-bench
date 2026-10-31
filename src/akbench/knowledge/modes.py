"""The three arms of a memory experiment (plan section 17)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeMode(StrEnum):
    """How one arm of the experiment treats knowledge."""

    LEARNING = "learning"
    REPLAY = "replay"
    FRESH = "fresh"

    @property
    def reads_knowledge(self) -> bool:
        return self is KnowledgeMode.REPLAY

    @property
    def writes_knowledge(self) -> bool:
        """Only the learning arm writes.

        A replay that also writes would feed its own result back into the
        knowledge base, so the second replay would not measure the first one.
        """
        return self is KnowledgeMode.LEARNING

    @property
    def needs_learning_session(self) -> bool:
        return self is KnowledgeMode.REPLAY

    @property
    def requires_clean_session(self) -> bool:
        """Every arm starts a new agent session; only fresh and replay are new."""
        return self in (KnowledgeMode.REPLAY, KnowledgeMode.FRESH)


class TransferScenario(StrEnum):
    """What relationship the tested task has with the learned knowledge."""

    EXACT_REPLAY = "exact_replay"
    RELATED_TRANSFER = "related_transfer"
    NEGATIVE_TRANSFER = "negative_transfer"

    @property
    def task_must_be_in_learning_set(self) -> bool:
        """An exact replay is the same task; a transfer is a different one.

        The distinction is what makes the two comparable: an exact replay
        measures recall of the same problem, a transfer measures whether the
        knowledge moved to a neighbouring problem at all.
        """
        return self is TransferScenario.EXACT_REPLAY

    @property
    def knowledge_is_expected_to_help(self) -> bool:
        """A negative transfer is expected to hurt; it is not a bug to fix.

        Keeping the scenario explicit stops a regression in the negative case
        from being read as an improvement.
        """
        return self in (TransferScenario.EXACT_REPLAY, TransferScenario.RELATED_TRANSFER)


class ScenarioSpec(BaseModel):
    """One declared scenario of a memory experiment."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=128)
    type: TransferScenario
    task: str = Field(..., min_length=1, max_length=256)
    note: str | None = None


@dataclass(frozen=True)
class KnowledgeArm:
    """One runnable arm: a mode, optionally a scenario, and its identity.

    ``arm_id`` is stable across runs of the planner, so results can be joined
    to the arm that produced them without depending on the order of the plan.
    """

    arm_id: str
    mode: KnowledgeMode
    scenario: TransferScenario | None = None
    task_uid: str | None = None
    position: int = 0

    @property
    def is_control(self) -> bool:
        return self.mode is KnowledgeMode.FRESH

    def as_dict(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "mode": self.mode.value,
            "scenario": self.scenario.value if self.scenario else None,
            "task_uid": self.task_uid,
            "position": self.position,
        }

"""Model descriptor (plan sections 3.1 and 7.3).

An agent is not a model and a router is not a model. Some models are selected
explicitly, some by a router, and some are not observable at all; recording a
model is only allowed when there is trustworthy evidence for it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from akbench.descriptors.base import DescriptorBase
from akbench.descriptors.statuses import SupportLevel


class ModelSelection(StrEnum):
    """How this model ends up serving a request."""

    EXPLICIT = "explicit"
    ROUTER_ALIAS = "router_alias"
    DYNAMIC = "dynamic"
    HIDDEN = "hidden"


class ModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    runtime_id: str | None = None
    selection: ModelSelection = ModelSelection.EXPLICIT
    # Whether AK-Bench can name the model that actually served a request.
    observable: SupportLevel = SupportLevel.UNVERIFIED
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    tool_calling: bool | None = None
    aliases: list[str] = Field(default_factory=list)
    notes: str | None = None


class ModelDescriptor(DescriptorBase):
    """A model (or model alias) that experiments may reference."""

    model: ModelBody = Field(default_factory=ModelBody)

    @property
    def is_alias(self) -> bool:
        return self.model.selection is ModelSelection.ROUTER_ALIAS

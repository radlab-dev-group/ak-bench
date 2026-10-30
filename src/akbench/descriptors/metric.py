"""Metric descriptor (plan section 18).

Every metric states whether it can actually be computed. A metric with no
source is reported as ``unavailable`` rather than silently becoming zero —
that is the difference between a measurement and an invention.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from akbench.descriptors.base import DescriptorBase


class MetricGroup(StrEnum):
    QUALITY = "quality"
    EFFICIENCY = "efficiency"
    AGENT_RUNTIME = "agent_runtime"
    KNOWLEDGE = "knowledge"
    RELIABILITY = "reliability"


class Direction(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    NONE = "none"


class Availability(StrEnum):
    COMPUTED = "computed"
    DERIVED = "derived"
    UNAVAILABLE = "unavailable"


class MetricBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: MetricGroup = MetricGroup.QUALITY
    unit: str | None = None
    direction: Direction = Direction.NONE
    availability: Availability = Availability.COMPUTED
    # Sources the metric needs; names are resolved by the metrics layer.
    requires: list[str] = Field(default_factory=list)
    # Baselines: cost and token savings are meaningless without one.
    baseline_relative: bool = False
    unavailable_reason: str | None = None
    notes: str | None = None


class MetricDescriptor(DescriptorBase):
    """A metric definition, including whether it is computable at all."""

    metric: MetricBody

    @property
    def computable(self) -> bool:
        return self.metric.availability is not Availability.UNAVAILABLE

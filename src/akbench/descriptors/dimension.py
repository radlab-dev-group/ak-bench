"""Dimension descriptor (plan section 11).

A dimension is an experiment factor. Uncontrollable dimensions may be observed
but never generate variants, so factor eligibility is derived, not assumed.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from akbench.descriptors.base import DescriptorBase


class DimensionType(StrEnum):
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    AGENT_REFERENCE = "agent_reference"
    MODEL_REFERENCE = "model_reference"
    PLUGIN_CONFIGURATION = "plugin_configuration"
    RUNTIME_CONFIGURATION = "runtime_configuration"


REFERENCE_TYPES = {
    DimensionType.AGENT_REFERENCE,
    DimensionType.MODEL_REFERENCE,
    DimensionType.PLUGIN_CONFIGURATION,
    DimensionType.RUNTIME_CONFIGURATION,
}
RANGE_TYPES = {DimensionType.INTEGER, DimensionType.FLOAT}


class DimensionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: DimensionType
    source: str | None = None
    values: list[object] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    default: object | None = None
    controllable: bool = False
    observed: bool = True
    configure_via: str | None = None
    verify_via: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _check_value_space(self) -> DimensionBody:
        if self.type is DimensionType.BOOLEAN:
            if self.values not in (None, [False, True], [True, False]):
                raise ValueError("a boolean dimension may only list [true, false] as values")
            return self
        if self.type in RANGE_TYPES:
            bounds_are_set = self.minimum is not None and self.maximum is not None
            if bounds_are_set and self.minimum > self.maximum:
                raise ValueError("minimum must not exceed maximum")
            return self
        # categorical, string and reference types need an explicit value space
        # whenever they are meant to generate variants.
        if self.controllable and not self.values:
            raise ValueError(
                f"a controllable {self.type.value} dimension must declare allowed values"
            )
        if self.values is not None and not self.values:
            raise ValueError("values must not be an empty list")
        return self


class DimensionDescriptor(DescriptorBase):
    """An experiment factor."""

    dimension: DimensionBody

    @property
    def usable_as_factor(self) -> bool:
        """Only controllable dimensions with a value space vary between runs."""
        if not self.dimension.controllable:
            return False
        if self.dimension.type is DimensionType.BOOLEAN:
            return True
        return bool(self.dimension.values)

    def allowed_values(self) -> list[object]:
        if self.dimension.type is DimensionType.BOOLEAN:
            return [False, True]
        return list(self.dimension.values or [])

    def accepts(self, value: object) -> bool:
        values = self.allowed_values()
        if not values:
            return False
        return value in values

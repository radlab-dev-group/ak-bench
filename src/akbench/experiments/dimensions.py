"""Factor resolution against dimension descriptors (plan section 11).

A factor is an experiment dimension that is allowed to vary. Two rules decide
that, and both come from the descriptor rather than from the experiment:

- only a **controllable** dimension may generate variants — an uncontrollable
  one can be observed but not set, so a variant that "sets" it would be a
  claim rather than a configuration;
- a value must be **declared** by the dimension. A value the dimension does not
  list is rejected even when it looks plausible, because the dimension carries
  the verified value space (for instance the model ids the router really
  serves).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from akbench.core.errors import AKBenchmarkError
from akbench.descriptors import (
    DescriptorKind,
    DescriptorRegistry,
    DimensionDescriptor,
    DimensionType,
)
from akbench.descriptors.dimension import RANGE_TYPES


class DimensionResolutionError(AKBenchmarkError):
    """A factor cannot be resolved to a usable dimension descriptor."""


@dataclass(frozen=True)
class Factor:
    """One resolved factor: the dimension plus the values it may take."""

    id: str
    descriptor: DimensionDescriptor
    values: tuple[Any, ...]

    @property
    def type(self) -> DimensionType:
        return self.descriptor.dimension.type

    @property
    def configure_via(self) -> str | None:
        return self.descriptor.dimension.configure_via

    def accepts_value(self, value: Any) -> bool:
        """True when ``value`` is one this factor can actually take.

        The factor's own value space is decisive: a factor may narrow the
        dimension, and a baseline or combination that names a value outside that
        narrowing is not part of this experiment even though the dimension
        declares it.
        """
        if any(_same(value, candidate) for candidate in self.values):
            return True
        return not self.values and self.within_bounds(value)

    def within_bounds(self, value: Any) -> bool:
        """Range dimensions declare an interval instead of a list of values."""
        body = self.descriptor.dimension
        if body.type not in RANGE_TYPES:
            return False
        if isinstance(value, bool) or not isinstance(value, int | float):
            return False
        if body.minimum is None or body.maximum is None:
            return False
        return body.minimum <= value <= body.maximum

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "values": list(self.values),
            "source": self.descriptor.dimension.source,
            "controllable": self.descriptor.dimension.controllable,
            "configure_via": self.configure_via,
            "dimension_version": self.descriptor.version,
            "digest": self.descriptor.identity(),
        }


class DimensionRegistry:
    """Dimension descriptors resolved by id, with factor eligibility."""

    def __init__(self, registry: DescriptorRegistry) -> None:
        self._registry = registry

    def __len__(self) -> int:
        return len(self._registry.entries(DescriptorKind.DIMENSION))

    def ids(self) -> list[str]:
        entries = self._registry.entries(DescriptorKind.DIMENSION)
        return sorted({entry.snapshot.id for entry in entries})

    def resolve(self, dimension_id: str, version: str | None = None) -> DimensionDescriptor:
        entry = self._registry.get(DescriptorKind.DIMENSION, dimension_id, version)
        if entry is None:
            known = ", ".join(self.ids()) or "none"
            raise DimensionResolutionError(
                f"unknown dimension {dimension_id!r}; known dimensions: {known}"
            )
        if not isinstance(entry.descriptor, DimensionDescriptor):  # pragma: no cover
            raise DimensionResolutionError(f"{dimension_id!r} is not a dimension descriptor")
        return entry.descriptor

    def factor(
        self,
        dimension_id: str,
        values: list[Any] | None = None,
        version: str | None = None,
    ) -> Factor:
        """Resolve ``dimension_id`` into a factor, validating its value space."""
        descriptor = self.resolve(dimension_id, version)

        if not descriptor.dimension.controllable:
            raise DimensionResolutionError(
                f"dimension {dimension_id!r} cannot be a factor: it is not controllable. "
                "Uncontrollable dimensions may be observed, never varied (plan 11)"
            )

        allowed = descriptor.allowed_values()
        is_range = descriptor.dimension.type in RANGE_TYPES
        requested = list(values) if values else list(allowed)
        if not requested:
            hint = (
                "list the values to try in the experiment factor"
                if is_range
                else "list them in the dimension descriptor or in the experiment factor"
            )
            raise DimensionResolutionError(
                f"dimension {dimension_id!r} declares no value space; {hint}"
            )
        for value in requested:
            if allowed and not any(_same(value, candidate) for candidate in allowed):
                raise DimensionResolutionError(
                    f"value {value!r} is not allowed for dimension {dimension_id!r}; "
                    f"allowed: {allowed}"
                )
            if is_range and not _within(descriptor, value):
                body = descriptor.dimension
                raise DimensionResolutionError(
                    f"value {value!r} is outside the bounds of dimension "
                    f"{dimension_id!r} ({body.minimum}..{body.maximum})"
                )
        if len(set(map(_hashable, requested))) < len(requested):
            raise DimensionResolutionError(
                f"dimension {dimension_id!r} lists duplicate values"
            )
        return Factor(id=dimension_id, descriptor=descriptor, values=tuple(requested))


def _within(descriptor: DimensionDescriptor, value: Any) -> bool:
    body = descriptor.dimension
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    if body.minimum is None or body.maximum is None:
        return False
    return body.minimum <= value <= body.maximum


def _same(left: Any, right: Any) -> bool:
    """``True`` and ``1`` stay different, so a boolean factor cannot merge with an int."""
    return type(left) is type(right) and left == right


def _hashable(value: Any) -> Any:
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value

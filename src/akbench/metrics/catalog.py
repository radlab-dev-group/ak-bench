"""The metric catalog: every metric definition the project ships, in one place.

The catalog is built from Metric Descriptors, so "which metrics exist and which
of them can actually be computed" is data, not code. A metric that the
descriptor marks ``unavailable`` stays unavailable here: the catalog reports
the reason instead of inventing a source.
"""

from __future__ import annotations

from pathlib import Path

from akbench.core.errors import DescriptorError
from akbench.descriptors import (
    DescriptorKind,
    DescriptorRegistry,
    MetricDescriptor,
    load_registry,
)


class MetricCatalog:
    """Indexed access to the loaded Metric Descriptors."""

    def __init__(self, descriptors: list[MetricDescriptor]) -> None:
        self._by_id: dict[str, MetricDescriptor] = {}
        for descriptor in descriptors:
            if descriptor.id in self._by_id:
                raise DescriptorError(f"duplicate metric descriptor: {descriptor.id}")
            self._by_id[descriptor.id] = descriptor

    @classmethod
    def from_registry(cls, registry: DescriptorRegistry) -> MetricCatalog:
        return cls([item.descriptor for item in registry.entries(DescriptorKind.METRIC)])

    @classmethod
    def load(cls, descriptors_dir: Path) -> MetricCatalog:
        return cls.from_registry(load_registry(Path(descriptors_dir)))

    def get(self, metric_id: str) -> MetricDescriptor:
        try:
            return self._by_id[metric_id]
        except KeyError:
            raise KeyError(f"unknown metric: {metric_id}") from None

    def has(self, metric_id: str) -> bool:
        return metric_id in self._by_id

    def all(self) -> list[MetricDescriptor]:
        return list(self._by_id.values())

    def by_group(self, group: str) -> list[MetricDescriptor]:
        return [item for item in self._by_id.values() if item.metric.group.value == group]

    def computable(self) -> list[MetricDescriptor]:
        return [item for item in self._by_id.values() if item.computable]

    def unavailable(self) -> list[MetricDescriptor]:
        return [item for item in self._by_id.values() if not item.computable]

    def names(self) -> list[str]:
        return list(self._by_id)

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {
            metric.id: {
                "title": metric.title,
                "group": metric.metric.group.value,
                "unit": metric.metric.unit,
                "direction": metric.metric.direction.value,
                "availability": metric.metric.availability.value,
                "baseline_relative": metric.metric.baseline_relative,
                "requires": list(metric.metric.requires),
                "unavailable_reason": metric.metric.unavailable_reason,
            }
            for metric in self._by_id.values()
        }

"""Plugin adapter registry.

Adapters are keyed by plugin provider, because that is the field a Plugin
Descriptor uses to say where the plugin runs. Selecting by id instead would
force a code change for every new plugin of a kind AK-Bench already supports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from akbench.descriptors.plugin import PluginDescriptor
from akbench.plugins.adapter import LlmRouterPluginAdapter
from akbench.plugins.contract import PluginAdapter, PluginAdapterError, PluginReport


class PluginRegistry:
    """Maps a plugin descriptor to the adapter that can handle it."""

    def __init__(self, adapters: Iterable[PluginAdapter] = ()) -> None:
        self._adapters: list[PluginAdapter] = []
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: PluginAdapter) -> None:
        """Register an adapter; a second adapter for the same id replaces it."""
        self._adapters = [item for item in self._adapters if item.adapter_id != adapter.adapter_id]
        self._adapters.append(adapter)

    @property
    def adapters(self) -> list[PluginAdapter]:
        return list(self._adapters)

    def resolve(self, descriptor: PluginDescriptor) -> PluginAdapter:
        """The adapter for ``descriptor``, or a loud failure.

        Falling back to a generic adapter would silently produce empty state,
        which is indistinguishable from a plugin that is switched off — so the
        registry refuses instead.
        """
        for adapter in self._adapters:
            if adapter.supports(descriptor):
                return adapter
        raise PluginAdapterError(
            f"plugin {descriptor.id}: no adapter handles provider "
            f"{descriptor.plugin.provider!r}; registered adapters: "
            + (", ".join(sorted(adapter.adapter_id for adapter in self._adapters)) or "none")
        )

    def supports(self, descriptor: PluginDescriptor) -> bool:
        return any(adapter.supports(descriptor) for adapter in self._adapters)

    def reports(
        self,
        descriptors: Iterable[PluginDescriptor],
        requested: Mapping[str, Mapping[str, Any]] | None = None,
        environ: Mapping[str, str] | None = None,
        digests: Mapping[str, str] | None = None,
    ) -> list[PluginReport]:
        """Build a report per descriptor, keyed requests by plugin id.

        An unsupported plugin is reported, not skipped: "no adapter" is a
        finding, and dropping the row would hide it.
        """
        wanted = dict(requested or {})
        known = {item.id for item in descriptors}
        unknown = sorted(set(wanted) - known)
        if unknown:
            raise PluginAdapterError(
                "requested configuration for plugins that were not passed: "
                + ", ".join(unknown)
            )

        reports: list[PluginReport] = []
        for descriptor in descriptors:
            digest = (digests or {}).get(descriptor.id)
            if not self.supports(descriptor):
                reports.append(
                    PluginReport(
                        plugin_id=descriptor.id,
                        plugin_version=descriptor.version,
                        digest=digest,
                        enabled=False,
                        note=(
                            f"no adapter handles provider {descriptor.plugin.provider!r}; "
                            "this plugin cannot be observed or verified"
                        ),
                    )
                )
                continue
            adapter = self.resolve(descriptor)
            reports.append(
                adapter.report(
                    descriptor,
                    digest=digest,
                    requested=wanted.get(descriptor.id),
                    environ=environ,
                )
            )
        return reports


def build_plugin_registry(
    descriptors: Iterable[PluginDescriptor] = (),
    *,
    config_readers: Mapping[str, Any] | None = None,
    metric_sources: Mapping[str, Mapping[str, Any]] | None = None,
) -> PluginRegistry:
    """Registry wired with the adapters the shipped plugins need.

    ``config_readers`` and ``metric_sources`` are keyed by plugin id and carry
    evidence a caller managed to obtain (a host-side configuration file, a
    counter export). On a shared external router they stay empty, which is the
    honest default rather than a limitation of this function.
    """
    registry = PluginRegistry([LlmRouterPluginAdapter()])
    readers = dict(config_readers or {})
    sources = dict(metric_sources or {})
    known = {descriptor.id for descriptor in descriptors}

    unknown = sorted((set(readers) | set(sources)) - known)
    if unknown:
        raise PluginAdapterError(
            "evidence sources provided for plugins that are not registered: "
            + ", ".join(unknown)
        )

    for plugin_id in sorted(set(readers) | set(sources)):
        adapter = LlmRouterPluginAdapter(
            config_reader=readers.get(plugin_id),
            metric_source=sources.get(plugin_id),
        )
        registry.register(adapter)
    return registry

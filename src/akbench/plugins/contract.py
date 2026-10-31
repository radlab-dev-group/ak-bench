"""The plugin adapter contract (plan section 10.3).

A :class:`PluginAdapter` is the only component allowed to touch a concrete
plugin: it owns reading, writing, verifying and interpreting that plugin, so
none of that knowledge may leak into the experiment engine.

Honesty rules that every adapter must obey:

- only environment variables declared in the descriptor's ``observed_env``
  allowlist may be read; secrets are reduced to ``is_set`` (plan 10.1);
- presence of an environment variable or configuration entry is *not* proof
  the plugin works, so verification is an explicit, separate step and its
  result is a status, not a boolean (plan 10.2);
- a metric the plugin does not expose is ``unavailable`` with a reason, never
  zero (plan section 18).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from akbench.core.errors import AKBenchmarkError
from akbench.descriptors.plugin import PluginDescriptor, PluginState


class PluginAdapterError(AKBenchmarkError):
    """A plugin adapter could not carry out an operation."""


@dataclass(frozen=True)
class PluginMetric:
    """One metric attributed to one plugin.

    ``value`` is ``None`` whenever the metric cannot be measured, and
    ``available`` records that honestly instead of reporting zero.
    """

    name: str
    value: Any | None = None
    unit: str | None = None
    available: bool = True
    reason: str | None = None
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "available": self.available,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True)
class PluginReport:
    """Everything AK-Bench knows about one plugin for one run.

    The state follows the requested/configured/effective/observed chain of
    plan section 10.2; ``verification_status`` applies to the plugin as a
    whole and is never inferred from the presence of configuration.
    """

    plugin_id: str
    plugin_version: str
    digest: str | None = None
    enabled: bool = False
    state: PluginState | None = None
    metrics: list[PluginMetric] = field(default_factory=list)
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "digest": self.digest,
            "enabled": self.enabled,
            "state": self.state.model_dump(mode="json") if self.state else None,
            "metrics": [metric.as_dict() for metric in self.metrics],
            "note": self.note,
        }


@runtime_checkable
class PluginAdapter(Protocol):
    """What the engine may ask of any plugin adapter (plan 10.3)."""

    adapter_id: str

    def supports(self, descriptor: PluginDescriptor) -> bool:
        """Whether this adapter can handle the plugin the descriptor describes."""
        ...

    def observe(
        self,
        descriptor: PluginDescriptor,
        requested: Mapping[str, Any] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> PluginState:
        """Read the allowlisted inputs and build the per-run plugin state.

        ``requested`` carries what the experiment asked for (dimension values);
        ``environ`` is the environment to read from (the process environment by
        default). Observation never claims verification.
        """
        ...

    def verify(self, descriptor: PluginDescriptor, state: PluginState) -> PluginState:
        """Run the plugin's verification and stamp the result on the state.

        An adapter that cannot verify a plugin must return the state with
        ``unverified`` (or ``unsupported``), never ``verified``.
        """
        ...

    def normalize_metrics(
        self,
        descriptor: PluginDescriptor,
        state: PluginState,
    ) -> list[PluginMetric]:
        """Return the plugin's declared metrics with whatever can be measured."""
        ...

    def report(
        self,
        descriptor: PluginDescriptor,
        digest: str | None = None,
        requested: Mapping[str, Any] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> PluginReport:
        """Observe, verify and normalize in one call."""
        ...

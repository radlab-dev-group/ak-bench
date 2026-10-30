"""Agent Registry (plan section 6.1).

The registry is where agent *types* are born. An entry pairs an Agent
Descriptor (what the agent claims) with an adapter factory (what the agent
actually does). The engine resolves agents by id and version exactly like any
other descriptor, checks required capabilities against the descriptor, and
instantiates adapters through the factory — no experiment code ever imports
a concrete adapter.

Adding a new agent means: add its descriptor, register its adapter, pass the
contract tests. Nothing in the runner changes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from akbench.agents.contract import AgentAdapter, AgentConfig
from akbench.agents.errors import AgentError
from akbench.descriptors.agent import AgentDescriptor
from akbench.descriptors.registry import DescriptorRegistry

AdapterFactory = Callable[[AgentDescriptor], AgentAdapter]


@dataclass(frozen=True)
class AgentEntry:
    """One registered agent: descriptor, adapter factory and provenance."""

    descriptor: AgentDescriptor
    factory: AdapterFactory

    @property
    def identity(self) -> str:
        return self.descriptor.identity()

    @property
    def id(self) -> str:
        return self.descriptor.id

    @property
    def adapter_id(self) -> str:
        return self.descriptor.agent.adapter

    def adapter(self) -> AgentAdapter:
        """Build a fresh adapter instance. Adapters are never shared between runs."""
        return self.factory(self.descriptor)

    def check_capabilities(self, required: Iterable[str]) -> list[str]:
        """Names from ``required`` this agent cannot provide (plan 6.4)."""
        return self.descriptor.missing_capabilities(list(required))


class AgentRegistry:
    """Holds agent entries and resolves them like any descriptor identity."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], AgentEntry] = {}

    def register(self, descriptor: AgentDescriptor, factory: AdapterFactory) -> AgentEntry:
        """Register an agent. Re-registering the same identity replaces it,
        which keeps test fixtures and plugin loading idempotent."""
        key = (descriptor.id, descriptor.version)
        entry = AgentEntry(descriptor=descriptor, factory=factory)
        self._entries[key] = entry
        return entry

    def entries(self) -> list[AgentEntry]:
        return [self._entries[key] for key in sorted(self._entries)]

    def resolve(self, agent_id: str, version: str | None = None) -> AgentEntry:
        """Resolve ``id`` at ``version`` (or the newest version when omitted)."""
        if version is None:
            versions = {key[1] for key in self._entries if key[0] == agent_id}
            if not versions:
                raise AgentError(f"no agent registered with id {agent_id!r}")
            version = max(versions)
        key = (agent_id, version)
        if key not in self._entries:
            raise AgentError(f"agent {agent_id}@{version} is not registered")
        return self._entries[key]

    def from_descriptor_registry(self, registry: DescriptorRegistry) -> list[AgentDescriptor]:
        """All agent descriptors from a loaded descriptor registry, in order."""
        return [
            entry.descriptor
            for entry in registry.entries()
            if isinstance(entry.descriptor, AgentDescriptor)
        ]

    def __len__(self) -> int:
        return len(self._entries)


def validate_agent_config(descriptor: AgentDescriptor, config: AgentConfig) -> None:
    """Validate an ``AgentConfig`` against the descriptor's schema (plan 6.7).

    Rules:
    - every parameter must be declared in ``configuration_schema``;
    - non-controllable parameters may not be set by an experiment;
    - ``allowed`` values are enforced when declared;
    - the declared type is enforced for scalar values.
    """
    from akbench.descriptors.agent import _type_matches

    schema = descriptor.agent.configuration_schema
    for name, value in config.parameters.items():
        parameter = schema.get(name)
        if parameter is None:
            raise AgentError(
                f"agent {descriptor.id}: unknown configuration parameter {name!r}; "
                f"declared: {sorted(schema) or 'none'}"
            )
        if not parameter.controllable:
            raise AgentError(
                f"agent {descriptor.id}: parameter {name!r} is not controllable by experiments"
            )
        if parameter.allowed is not None and value not in parameter.allowed:
            raise AgentError(
                f"agent {descriptor.id}: value {value!r} for {name!r} "
                f"is not in the allowed set {parameter.allowed}"
            )
        if value is not None and not _type_matches(value, parameter.type):
            raise AgentError(
                f"agent {descriptor.id}: value {value!r} for {name!r} "
                f"does not match declared type {parameter.type!r}"
            )

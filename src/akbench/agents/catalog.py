"""Where agent adapters are declared (plan 6.1, step 5: registration).

This is the single plug-in point of the agent layer. ``ADAPTER_TYPES`` maps the
``agent.adapter`` id written in a descriptor to the class that implements the
contract; :func:`build_agent_registry` pairs every Agent Descriptor on disk with
its adapter, and refuses to register an agent whose adapter is unknown.

Adding an agent therefore means: a descriptor, an adapter class, one entry in
this map, and contract tests. The runner, scheduler and evaluators stay
untouched, and no experiment code names an agent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from akbench.agents.codex import CodexAdapter, CodexOptions
from akbench.agents.errors import AgentError
from akbench.agents.registry import AdapterFactory, AgentRegistry
from akbench.descriptors.agent import AgentDescriptor
from akbench.descriptors.runtime import RuntimeDescriptor

#: adapter id (as declared in a descriptor) -> adapter class.
ADAPTER_TYPES: dict[str, type] = {
    CodexAdapter.adapter_id: CodexAdapter,
}


@dataclass(frozen=True)
class AdapterOptions:
    """Constructor keyword arguments for one adapter, keyed by adapter id."""

    kwargs: Mapping[str, Any] = field(default_factory=dict)


def adapter_class(adapter_id: str) -> type:
    try:
        return ADAPTER_TYPES[adapter_id]
    except KeyError as exc:
        known = ", ".join(sorted(ADAPTER_TYPES)) or "none"
        raise AgentError(
            f"no adapter implementation for {adapter_id!r}; registered adapters: {known}. "
            "Add the class to akbench.agents.catalog.ADAPTER_TYPES."
        ) from exc


def default_factory(
    adapter_id: str,
    options: Mapping[str, Any] | None = None,
    *,
    adapter_class_: type | None = None,
) -> AdapterFactory:
    """Build a factory that instantiates the adapter with fixed options.

    ``adapter_class_`` lets tests (and plugin loaders) point at an adapter
    without registering it in :data:`ADAPTER_TYPES`; production callers rely on
    the catalog map.
    """

    implementation = adapter_class_ or adapter_class(adapter_id)
    bound = dict(options or {})

    def factory(descriptor: AgentDescriptor) -> Any:
        return implementation(descriptor, **bound)

    return factory


def build_agent_registry(
    descriptors: list[AgentDescriptor],
    options: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    allow_missing_adapter: bool = False,
) -> AgentRegistry:
    """Register every agent descriptor whose adapter is implemented.

    ``allow_missing_adapter`` keeps an agent registered with a factory that
    fails on use, so ``akbench agent list`` can still show an agent that is
    described but not yet implemented. Registration is never faked: the
    failure is explicit at run time.
    """
    registry = AgentRegistry()
    selection = dict(options or {})
    for descriptor in descriptors:
        adapter_id = descriptor.agent.adapter
        if adapter_id not in ADAPTER_TYPES:
            if not allow_missing_adapter:
                raise AgentError(
                    f"agent {descriptor.identity} declares adapter {adapter_id!r}, "
                    "which is not implemented"
                )
            registry.register(descriptor, _unimplemented_factory(adapter_id))
            continue
        registry.register(descriptor, default_factory(adapter_id, selection.get(adapter_id)))
    return registry


def _unimplemented_factory(adapter_id: str) -> AdapterFactory:
    def factory(descriptor: AgentDescriptor) -> Any:
        raise AgentError(
            f"agent {descriptor.identity} declares adapter {adapter_id!r}, "
            "which has no implementation in this installation"
        )

    return factory


def binding_from_runtime(runtime: RuntimeDescriptor) -> Any:
    """Derive the endpoint a runtime offers, without naming any agent.

    Only declared fields are used: the base address and the first required
    credential name. Nothing else is inferred, so an unlisted credential stays
    unset and surfaces later as a validation error rather than a guess.
    """
    from akbench.agents.contract import RuntimeBinding

    body = runtime.runtime
    return RuntimeBinding(
        runtime_id=runtime.id,
        base_url=body.base_url,
        api_key_env=body.required_env[0] if body.required_env else None,
    )


__all__ = [
    "ADAPTER_TYPES",
    "AdapterOptions",
    "CodexOptions",
    "adapter_class",
    "binding_from_runtime",
    "build_agent_registry",
    "default_factory",
]

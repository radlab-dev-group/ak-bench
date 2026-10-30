"""Runtime registry and execution-mode resolution (plan sections 7.1 and 7.2).

The registry pairs a Runtime Descriptor with the adapter that manages that
runtime, exactly as the agent registry does for agents: adding a runtime means
a descriptor plus one entry in ``RUNTIME_ADAPTER_TYPES``, never a change in the
runner.

:func:`plan_execution` implements plan 7.1: the experiment declares how the
agent reaches its model (``direct``, ``runtime`` or ``router``) and the planner
either produces the binding the agent adapter needs, or refuses with the
reason.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from akbench.descriptors.runtime import Lifecycle, RuntimeDescriptor
from akbench.runtime.contract import ExecutionMode, RuntimeManager
from akbench.runtime.errors import RuntimeError
from akbench.runtime.llm_router import LlmRouterAdapter

ManagerFactory = Callable[[RuntimeDescriptor], RuntimeManager]

#: descriptor ``runtime.adapter`` id -> adapter class.
RUNTIME_ADAPTER_TYPES: dict[str, type] = {
    LlmRouterAdapter.adapter_id: LlmRouterAdapter,
}


@dataclass(frozen=True)
class RuntimeEntry:
    """One registered runtime: descriptor plus the adapter that manages it."""

    descriptor: RuntimeDescriptor
    factory: ManagerFactory

    @property
    def identity(self) -> str:
        return self.descriptor.identity()

    @property
    def id(self) -> str:
        return self.descriptor.id

    @property
    def adapter_id(self) -> str:
        return self.descriptor.runtime.adapter

    def manager(self) -> RuntimeManager:
        return self.factory(self.descriptor)

    def supports(self, mode: ExecutionMode | str) -> bool:
        # The descriptor owns its own mode vocabulary; a plain value bridges them.
        return self.descriptor.supports_mode(ExecutionMode(mode).value)

    def supports_lifecycle(self, lifecycle: Lifecycle | str) -> bool:
        return self.descriptor.supports_lifecycle(Lifecycle(lifecycle))


class RuntimeRegistry:
    """Holds runtime entries and resolves them by id and version."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], RuntimeEntry] = {}

    def register(self, descriptor: RuntimeDescriptor, factory: ManagerFactory) -> RuntimeEntry:
        entry = RuntimeEntry(descriptor=descriptor, factory=factory)
        self._entries[(descriptor.id, descriptor.version)] = entry
        return entry

    def entries(self) -> list[RuntimeEntry]:
        return [self._entries[key] for key in sorted(self._entries)]

    def resolve(self, runtime_id: str, version: str | None = None) -> RuntimeEntry:
        if version is None:
            versions = {key[1] for key in self._entries if key[0] == runtime_id}
            if not versions:
                raise RuntimeError(f"no runtime registered with id {runtime_id!r}")
            version = max(versions)
        key = (runtime_id, version)
        if key not in self._entries:
            raise RuntimeError(f"runtime {runtime_id}@{version} is not registered")
        return self._entries[key]

    def __len__(self) -> int:
        return len(self._entries)


def default_manager_factory(
    adapter_id: str,
    options: Mapping[str, Any] | None = None,
    *,
    adapter_class_: type | None = None,
) -> ManagerFactory:
    """Build a factory that instantiates the adapter with fixed options."""
    implementation = adapter_class_ or _adapter_class(adapter_id)
    bound = dict(options or {})

    def factory(descriptor: RuntimeDescriptor) -> Any:
        return implementation(descriptor, **bound)

    return factory


def _adapter_class(adapter_id: str) -> type:
    try:
        return RUNTIME_ADAPTER_TYPES[adapter_id]
    except KeyError as exc:
        known = ", ".join(sorted(RUNTIME_ADAPTER_TYPES)) or "none"
        raise RuntimeError(
            f"no runtime adapter implementation for {adapter_id!r}; "
            f"registered adapters: {known}"
        ) from exc


def build_runtime_registry(
    descriptors: Iterable[RuntimeDescriptor],
    options: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    allow_missing_adapter: bool = False,
) -> RuntimeRegistry:
    """Register every runtime descriptor whose adapter is implemented."""
    registry = RuntimeRegistry()
    selection = dict(options or {})
    for descriptor in descriptors:
        adapter_id = descriptor.runtime.adapter
        if adapter_id not in RUNTIME_ADAPTER_TYPES:
            if not allow_missing_adapter:
                raise RuntimeError(
                    f"runtime {descriptor.identity()} declares adapter {adapter_id!r}, "
                    "which is not implemented"
                )
            registry.register(descriptor, _unimplemented_manager_factory(adapter_id))
            continue
        registry.register(
            descriptor,
            default_manager_factory(adapter_id, selection.get(adapter_id)),
        )
    return registry


def _unimplemented_manager_factory(adapter_id: str) -> ManagerFactory:
    def factory(descriptor: RuntimeDescriptor) -> Any:
        raise RuntimeError(
            f"runtime {descriptor.identity()} declares adapter {adapter_id!r}, "
            "which has no implementation in this installation"
        )

    return factory


@dataclass(frozen=True)
class RuntimePlan:
    """The declared execution mode, resolved against the registries.

    ``binding`` is what an agent adapter is told about the endpoint; for
    ``direct`` it is ``None`` by construction, because there is no endpoint.
    """

    mode: ExecutionMode
    runtime: RuntimeEntry | None = None
    binding: Any = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "runtime": self.runtime.identity if self.runtime else None,
            "base_url": getattr(self.binding, "base_url", None),
            "credential_env": getattr(self.binding, "api_key_env", None),
            "provenance": dict(self.provenance),
        }


def plan_execution(
    mode: ExecutionMode | str,
    runtime_id: str | None,
    registry: RuntimeRegistry,
    *,
    lifecycle: Lifecycle | str | None = None,
) -> RuntimePlan:
    """Resolve the declared execution mode (plan 7.1).

    ``direct`` must not name a runtime, and ``runtime``/``router`` must name one
    that declares support for the mode. A wrong combination is an error, not a
    silent downgrade: an experiment that thinks it is routed but is not would
    produce unusable results.
    """
    from akbench.agents.contract import RuntimeBinding

    resolved_mode = ExecutionMode(mode)
    if resolved_mode is ExecutionMode.DIRECT:
        if runtime_id:
            raise RuntimeError(
                f"execution mode {resolved_mode.value!r} must not name a runtime "
                f"({runtime_id!r} was given)"
            )
        return RuntimePlan(
            mode=resolved_mode,
            provenance={"reason": "no runtime in this mode"},
        )

    if not runtime_id:
        raise RuntimeError(
            f"execution mode {resolved_mode.value!r} requires --runtime RUNTIME"
        )

    entry = registry.resolve(runtime_id)
    if not entry.supports(resolved_mode):
        supported = ", ".join(mode.value for mode in entry.descriptor.runtime.execution_modes)
        raise RuntimeError(
            f"runtime {entry.identity} does not support mode {resolved_mode.value!r}; "
            f"it declares: {supported}"
        )
    if lifecycle is not None and not entry.supports_lifecycle(lifecycle):
        supported = ", ".join(item.value for item in entry.descriptor.runtime.supported_lifecycles)
        raise RuntimeError(
            f"runtime {entry.identity} does not support lifecycle {Lifecycle(lifecycle).value!r}; "
            f"it declares: {supported}"
        )

    body = entry.descriptor.runtime
    binding = RuntimeBinding(
        runtime_id=entry.id,
        base_url=body.base_url,
        api_key_env=body.required_env[0] if body.required_env else None,
    )
    return RuntimePlan(
        mode=resolved_mode,
        runtime=entry,
        binding=binding,
        provenance={
            "lifecycles": [item.value for item in body.supported_lifecycles],
            "healthcheck_path": body.healthcheck_path,
            "modes": [item.value for item in body.execution_modes],
        },
    )

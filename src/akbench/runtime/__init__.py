"""Runtime layer: execution modes, the manager contract and runtime adapters.

An agent may run ``direct`` (no runtime), through an intermediate runtime, or
through a router (plan 7.1). A runtime manager is a per-runtime adapter: it
knows how to start, stop, healthcheck and verify *that* runtime, while the
engine only sees the contract. The LLM Router adapter (``llm_router``) is the
first implementation.

The configuration triad of plan section 13 (requested / effective / observed
plus a verification status) is a first class model here, so a run can record how
much of its configuration was actually confirmed.
"""

from akbench.runtime.contract import (
    ExecutionMode,
    Lifecycle,
    RuntimeConfigReport,
    RuntimeManager,
    RuntimeState,
    VerificationStatus,
)
from akbench.runtime.llm_router import LlmRouterAdapter, LlmRouterOptions
from akbench.runtime.registry import (
    RuntimeEntry,
    RuntimePlan,
    RuntimeRegistry,
    build_runtime_registry,
    default_manager_factory,
    plan_execution,
)

__all__ = [
    "ExecutionMode",
    "Lifecycle",
    "LlmRouterAdapter",
    "LlmRouterOptions",
    "RuntimeConfigReport",
    "RuntimeEntry",
    "RuntimeManager",
    "RuntimePlan",
    "RuntimeRegistry",
    "RuntimeState",
    "VerificationStatus",
    "build_runtime_registry",
    "default_manager_factory",
    "plan_execution",
]

"""Run Orchestrator (plan section 15).

The orchestrator drives one run through its lifecycle using only the generic
contracts: the Agent Adapter, the optional Runtime Manager, the Workspace
Manager and the Evaluator Engine. It contains no knowledge of any concrete
agent, which is the point of the adapter layer (plan 15: the orchestrator must
not know Codex specifics).

A run is one task attempted by one agent in one workspace, in one execution
mode. It is recorded as it progresses, so a crash or a deliberate stop leaves a
resumable, inspectable state rather than a mystery.
"""

from akbench.orchestration.lifecycle import (
    RunContext,
    RunOutcome,
    RunState,
    transition_allowed,
)
from akbench.orchestration.orchestrator import OrchestrationConfig, RunOrchestrator

__all__ = [
    "OrchestrationConfig",
    "RunContext",
    "RunOrchestrator",
    "RunOutcome",
    "RunState",
    "transition_allowed",
]

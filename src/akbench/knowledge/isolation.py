"""What a memory experiment can isolate, and what it cannot (plan section 14).

A replay arm must not see anything of the learning arm except the knowledge
that was written. That means isolating, in addition to the usual per-run
workspace and session: the agent history, local caches, processes, and the
plugin's data spaces.

Whether the *knowledge namespace* can be isolated depends on the plugin and
the deployment, not on the experiment author: it is a property of the
environment, so it is reported as a finding with its status rather than
assumed. On the shared external router the namespace is not controllable, so
every experiment on that router shares one knowledge namespace and the report
says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from akbench.descriptors.plugin import PluginDescriptor
from akbench.descriptors.statuses import SupportLevel


@dataclass(frozen=True)
class IsolationReport:
    """The isolation facts of one memory experiment, per arm.

    ``namespace_isolated`` is the one that decides whether two experiments can
    run at all on the same router instance: if the namespace is shared, a
    learning run and a replay run on that instance see each other's knowledge
    through the plugin, not through the harness.
    """

    workspace_per_run: bool = True
    fresh_agent_session: bool = True
    clean_agent_context: bool = True
    agent_history_isolated: bool = True
    local_caches_isolated: bool = True
    namespace_isolated: SupportLevel = SupportLevel.UNSUPPORTED
    namespace_reason: str | None = None

    @property
    def arm_isolated(self) -> bool:
        """Whether a single arm is isolated from the other arms of the run."""
        return (
            self.workspace_per_run
            and self.fresh_agent_session
            and self.clean_agent_context
            and self.agent_history_isolated
            and self.local_caches_isolated
        )

    @property
    def comparable(self) -> bool:
        """Whether replay and fresh are comparable on this deployment."""
        return self.arm_isolated and self.namespace_isolated is SupportLevel.SUPPORTED

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspace_per_run": self.workspace_per_run,
            "fresh_agent_session": self.fresh_agent_session,
            "clean_agent_context": self.clean_agent_context,
            "agent_history_isolated": self.agent_history_isolated,
            "local_caches_isolated": self.local_caches_isolated,
            "namespace_isolated": self.namespace_isolated.value,
            "namespace_reason": self.namespace_reason,
            "comparable": self.comparable,
        }


def namespace_isolation(
    descriptor: PluginDescriptor | None,
    lifecycle: str | None,
) -> tuple[SupportLevel, str | None]:
    """Can the plugin's knowledge namespace be scoped to one experiment?

    Two things must be true: the plugin must expose a namespace variable, and
    that variable must be controllable (settable per run). The shipped
    knowledge descriptor declares its namespace variables as observable but not
    controllable, so on a router AK-Bench does not start the namespace is
    shared; on a managed instance the harness owns the environment and the
    namespace can be scoped.
    """
    if descriptor is None:
        return SupportLevel.UNSUPPORTED, "the plugin descriptor is not loaded"

    namespace_entries = [
        entry
        for entry in descriptor.benchmark.observed_env
        if "COLLECTION" in entry.name or "KEY_PREFIX" in entry.name
    ]
    if not namespace_entries:
        return SupportLevel.UNSUPPORTED, "the plugin declares no knowledge-namespace variable"

    controllable = [entry.name for entry in namespace_entries if entry.controllable]
    if controllable:
        return (
            SupportLevel.SUPPORTED,
            f"namespace can be scoped via {' / '.join(controllable)} on a managed instance",
        )
    if lifecycle == "managed":
        return (
            SupportLevel.SUPPORTED,
            (
                "the harness owns the managed instance's environment, so the namespace "
                "can be set per experiment even though the plugin does not expose an "
                "override for it"
            ),
        )
    return (
        SupportLevel.UNSUPPORTED,
        (
            "the plugin's namespace is not controllable and the router instance is not "
            "managed: all experiments on that instance share one knowledge namespace"
        ),
    )


def build_isolation_report(
    plugin: PluginDescriptor | None = None,
    lifecycle: str | None = None,
) -> IsolationReport:
    """Assemble the report for one memory experiment on one deployment."""
    level, reason = namespace_isolation(plugin, lifecycle)
    return IsolationReport(namespace_isolated=level, namespace_reason=reason)

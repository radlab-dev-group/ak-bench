"""Environment descriptor (plan section 9, 14).

An experiment runs somewhere: on the operator's machine, in a container, or in
a sandbox that does not yet exist. Before phase B there is only the host, and
this descriptor exists so that "where" is a declared, versioned, snapshot-able
fact instead of an assumption — the same way a runtime descriptor declares the
router rather than the run discovering it.

What the descriptor says is the contract the environment owes the run: the
operating system and interpreter the tasks assume, the tools the evaluators
may need, and what the operator is willing to give up (network, filesystem
scope) and how much (limits). It does not promise enforcement: phase B brings
the docker sandbox, and until then the run's manifest records ``host`` and the
limits are the operator's word, stated rather than silent.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from akbench.descriptors.base import DescriptorBase


class SandboxKind(StrEnum):
    """Where a run's process may execute (plan 14, phase B is the docker one)."""

    HOST = "host"
    DOCKER = "docker"


class EnvironmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The operating system the tasks assume. A task written for one is not
    #: portable to the other by renaming paths.
    os: str = Field(default="linux", min_length=1)
    #: The interpreter the tasks and their hidden tests run on.
    python: str = Field(default="3.12", min_length=1)
    #: Tools the evaluators may invoke (``git``, ``ruff``, ...). They are a
    #: contract for the operator, not a guarantee: ``doctor`` reports what is
    #: actually installed.
    tools: list[str] = Field(default_factory=list)
    #: Whether the agent may reach the network. ``true`` is the host default
    #: today; a docker sandbox (phase B) is where ``false`` becomes enforced.
    network: bool = True
    #: What the agent may write to. ``workspace`` is the isolation contract of
    #: plan 14; ``full`` is an explicit choice, recorded in the manifest.
    filesystem: str = Field(default="workspace", pattern=r"^(workspace|full)$")
    #: Where the run's process executes. ``host`` until phase B exists.
    sandbox: SandboxKind = SandboxKind.HOST
    #: A docker image, when the sandbox is docker. Stated here, recorded in
    #: the run's manifest (``sandbox_image``), never guessed.
    image: str | None = None
    #: Resource ceilings for the run. Informational until the sandbox can
    #: enforce them; stated so a run's costs are comparable across machines.
    limits: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_sandbox(self) -> EnvironmentBody:
        if self.sandbox is SandboxKind.DOCKER and not self.image:
            raise ValueError(
                "a docker sandbox must declare its image; the manifest's "
                "sandbox_image is stated, never inferred"
            )
        if self.sandbox is SandboxKind.HOST and self.image:
            raise ValueError(
                "a host sandbox has no image; declare a docker sandbox to use one"
            )
        return self


class EnvironmentDescriptor(DescriptorBase):
    """The environment an experiment may declare its runs in."""

    environment: EnvironmentBody = Field(default_factory=EnvironmentBody)

    def supports_sandbox(self, sandbox: SandboxKind | str) -> bool:
        """Whether this environment runs in the asked-for kind of sandbox."""
        return self.environment.sandbox is SandboxKind(sandbox)

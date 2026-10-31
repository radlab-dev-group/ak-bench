"""Dataset layer (Phase 3): tasks, their repositories, workspaces and mutations.

A task is a stable, versioned definition of a benchmark problem. Its
repository state is pinned to a commit, hidden tests stay outside every agent
workspace, and a bug-fix mutation is a controlled, versioned patch that must be
proven to break the tests before the task is ever exposed to an agent.
"""

from __future__ import annotations

from akbench.datasets.dataset import Dataset, TaskLoadError
from akbench.datasets.repository import (
    RepositoryCheck,
    RepositoryManager,
)
from akbench.datasets.task import (
    Difficulty,
    MutationSpec,
    RepositorySpec,
    TaskDescriptor,
)
from akbench.datasets.workspace import PreparedWorkspace, WorkspaceManager

__all__ = [
    "Dataset",
    "Difficulty",
    "MutationSpec",
    "PreparedWorkspace",
    "RepositoryCheck",
    "RepositoryManager",
    "RepositorySpec",
    "TaskDescriptor",
    "TaskLoadError",
    "WorkspaceManager",
]

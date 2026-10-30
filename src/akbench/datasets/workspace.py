"""Workspace Manager (plan sections 8.6 and 14).

Every run gets its own checkout of the pinned commit, created as a git worktree
over a shared bare cache and detached from any branch. A bug-fix task then gets
its mutation applied on top. Two workspaces prepared from the same task
description have identical content — that fingerprint is the tree hash, and it
is what makes a workspace repeatable.

Hidden tests are never part of this: they live in the dataset directory and are
only ever read by the evaluator (plan 8.6).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from akbench.core.errors import WorkspaceError
from akbench.datasets.repository import RepositoryManager, _run_git
from akbench.datasets.task import TaskDescriptor


@dataclass(frozen=True)
class PreparedWorkspace:
    """What was created, and the fingerprints that make it reproducible.

    ``tree`` is the committed git tree (the pinned state), while
    ``fingerprint`` covers the working tree *including* applied mutations, which
    are deliberately left uncommitted so an agent never sees the defect in the
    git history.
    """

    workspace_id: str
    task_uid: str
    path: Path
    base_commit: str
    commit: str
    tree: str
    fingerprint: str
    mutation_applied: bool
    mutation_version: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "task_uid": self.task_uid,
            "path": str(self.path),
            "base_commit": self.base_commit,
            "commit": self.commit,
            "tree": self.tree,
            "fingerprint": self.fingerprint,
            "mutation_applied": self.mutation_applied,
            "mutation_version": self.mutation_version,
        }


class WorkspaceManager:
    """Creates and removes per-run workspaces from the bare repository cache."""

    def __init__(self, repositories: RepositoryManager, workspaces_dir: Path) -> None:
        self.repositories = repositories
        self.workspaces_dir = Path(workspaces_dir)

    def prepare(
        self,
        task: TaskDescriptor,
        workspace_id: str,
        *,
        task_dir: Path | None = None,
        apply_mutation: bool = True,
    ) -> PreparedWorkspace:
        """Create a detached worktree of the pinned commit, mutation included.

        ``task_dir`` locates the mutation patch when the task declares one; it
        is resolved by the caller because the dataset layout is not a property
        of a workspace.
        """
        spec = task.task.repository
        bare = self.repositories.ensure_cached(spec.source)
        base_commit = self.repositories.resolve_commit(bare, spec.ref)

        target = self.workspaces_dir / workspace_id
        if target.exists():
            raise WorkspaceError(
                f"workspace {workspace_id!r} already exists at {target}; "
                "workspaces are per run and are never reused"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["worktree", "add", "--detach", str(target), base_commit], cwd=bare)

        mutation_applied = False
        mutation_version: str | None = None
        if apply_mutation and task.task.mutation is not None:
            patch_path = self._patch_path(task, task_dir)
            _run_git(["apply", "--whitespace=warn", str(patch_path)], cwd=target)
            if not self._has_changes(target):
                raise WorkspaceError(
                    f"mutation patch {patch_path.name} applied but changed nothing in {target}"
                )
            mutation_applied = True
            mutation_version = task.task.mutation.version

        return PreparedWorkspace(
            workspace_id=workspace_id,
            task_uid=task.uid,
            path=target,
            base_commit=base_commit,
            commit=_run_git(["rev-parse", "HEAD"], cwd=target),
            tree=self.tree_hash(target),
            fingerprint=self.fingerprint(target),
            mutation_applied=mutation_applied,
            mutation_version=mutation_version,
        )

    def tree_hash(self, workspace: Path) -> str:
        """The committed git tree (the pinned state, before local changes)."""
        return _run_git(["rev-parse", "HEAD^{tree}"], cwd=workspace)

    def fingerprint(self, workspace: Path) -> str:
        """Digest of the working tree: committed state plus every local change.

        Mutations are applied to the working tree and never committed, so
        ``HEAD^{tree}`` alone would not see them. This fingerprint covers the
        committed tree, the full ``git diff HEAD`` and the content of untracked,
        non-ignored files — the exact bytes an agent would work on.
        """
        import hashlib

        digest = hashlib.sha256()
        digest.update(self.tree_hash(Path(workspace)).encode("utf-8"))
        digest.update(b"\0diff\0")
        digest.update(_run_git(["diff", "HEAD", "--binary"], cwd=workspace).encode("utf-8"))
        digest.update(b"\0untracked\0")
        listing = _run_git(["ls-files", "-o", "--exclude-standard", "-z"], cwd=workspace)
        for name in sorted(part for part in listing.split("\0") if part):
            path = Path(workspace) / name
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return f"sha256:{digest.hexdigest()}"

    def status(self, workspace: Path) -> dict[str, object]:
        """Short identity summary of an existing workspace."""
        return {
            "commit": _run_git(["rev-parse", "HEAD"], cwd=workspace),
            "tree": self.tree_hash(workspace),
            "fingerprint": self.fingerprint(workspace),
            "dirty": bool(_run_git(["status", "--porcelain"], cwd=workspace)),
        }

    def cleanup(self, workspace: Path, *, missing_ok: bool = True) -> None:
        """Remove a workspace and its worktree registration."""
        path = Path(workspace).resolve()
        if not path.exists():
            if missing_ok:
                return
            raise WorkspaceError(f"workspace does not exist: {path}")

        admin = self._administrative_gitdir(path)
        main_gitdir = self._main_gitdir(admin) if admin else None
        if admin is not None:
            _run_git(
                ["worktree", "remove", "--force", str(path)],
                cwd=path.parent,
                env={"GIT_DIR": str(admin)},
            )
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        if main_gitdir is not None:
            _run_git(["worktree", "prune"], cwd=path.parent, env={"GIT_DIR": str(main_gitdir)})

    def _patch_path(self, task: TaskDescriptor, task_dir: Path | None) -> Path:
        mutation = task.task.mutation
        if mutation is None:  # pragma: no cover - guarded by the caller
            raise WorkspaceError(f"task {task.uid} declares no mutation")
        if task_dir is None:
            raise WorkspaceError("task_dir is required to resolve a mutation patch")
        candidate = Path(task_dir) / mutation.patch
        if not candidate.is_file():
            raise WorkspaceError(f"mutation patch not found: {candidate}")
        return candidate

    @staticmethod
    def _has_changes(workspace: Path) -> bool:
        return bool(_run_git(["status", "--porcelain"], cwd=workspace))

    @staticmethod
    def _administrative_gitdir(workspace: Path) -> Path | None:
        """The admin gitdir a worktree points at (from its .git file)."""
        git_file = workspace / ".git"
        if not git_file.is_file():
            return None
        text = git_file.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir:"):
            return None
        return Path(text.split(":", 1)[1].strip()).resolve()

    @staticmethod
    def _main_gitdir(admin: Path | None) -> Path | None:
        """The repository gitdir that owns this worktree's registration.

        ``worktree remove`` deletes the admin directory, so prune must run
        against the main gitdir read from ``commondir`` before the removal.
        """
        if admin is None:
            return None
        commondir = admin / "commondir"
        if not commondir.is_file():
            return None
        relative = Path(commondir.read_text(encoding="utf-8").strip())
        return (admin / relative).resolve() if not relative.is_absolute() else relative.resolve()

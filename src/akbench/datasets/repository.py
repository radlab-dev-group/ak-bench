"""Repository handling: bare cache, ref resolution, integrity checks.

The base state of a task is a commit, never a branch name. Everything here is
plain git through ``subprocess``: AK-Bench keeps no custom repository format,
so a workspace can always be recreated with the git the user already has.

Two source kinds are supported:

- a git source (URL or a path to a git repository), cloned bare into the cache;
- a *seed directory* (a plain directory, no git metadata) used for fixtures.
  The cache is then built with a fixed identity and fixed commit timestamps, so
  the same content always produces the same commit. Real datasets should pin a
  commit in a real repository; a seed exists to keep examples honest and small.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from akbench.core.errors import WorkspaceError

GIT_TIMEOUT_SECONDS = 300
SEED_IDENTITY = {
    "GIT_AUTHOR_NAME": "akbench",
    "GIT_AUTHOR_EMAIL": "akbench@invalid",
    "GIT_COMMITTER_NAME": "akbench",
    "GIT_COMMITTER_EMAIL": "akbench@invalid",
    "GIT_AUTHOR_DATE": "1970-01-01T00:00:00 +0000",
    "GIT_COMMITTER_DATE": "1970-01-01T00:00:00 +0000",
}
SEED_DIGEST_FILE = "akbench-seed-digest"
SEED_REF = "HEAD"


def run_git(
    args: list[str],
    cwd: Path | None = None,
    *,
    env: dict[str, str] | None = None,
) -> str:
    """Run git and return stdout. Failures become WorkspaceError carrying git's reason."""
    merged_env = {**os.environ, **(env or {})}
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=merged_env,
        )
    except FileNotFoundError as exc:
        raise WorkspaceError("git is not available in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError(f"git {' '.join(args[:3])} timed out") from exc
    if completed.returncode != 0:
        command = " ".join(args[:2])
        detail = (completed.stderr or completed.stdout or "").strip()
        raise WorkspaceError(f"git {command} failed: {detail or f'exit {completed.returncode}'}")
    return completed.stdout.strip()


# Kept importable under the earlier name for the workspace module.
_run_git = run_git


@dataclass(frozen=True)
class RepositoryCheck:
    """Outcome of validating a task repository for a task."""

    ok: bool
    source: str
    ref: str
    commit: str | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "source": self.source,
            "ref": self.ref,
            "commit": self.commit,
            "detail": self.detail,
        }


def slug_for_source(source: str) -> str:
    """Filesystem-safe, stable cache name for a repository source."""
    normalized = source.rstrip("/")
    tail = normalized.split("/")[-1] or normalized
    stem = re.sub(r"\.git$", "", tail)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", stem) or "repo"
    return f"{safe}-{digest}"


def is_git_repository(path: Path) -> bool:
    probe = Path(path)
    if not probe.is_dir():
        return False
    return (probe / ".git").exists() or (probe / "HEAD").is_file()


def is_seed_directory(source: str) -> bool:
    """True for a local directory that is not a git repository."""
    if "://" in source or source.startswith("git@"):
        return False
    probe = Path(source).expanduser()
    return probe.is_dir() and not is_git_repository(probe)


def directory_digest(directory: Path) -> str:
    """Content fingerprint of a directory, independent of file order and mtimes."""
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(directory).rglob("*") if p.is_file()):
        if path.name == ".git":
            continue
        digest.update(str(path.relative_to(directory)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class RepositoryManager:
    """Keeps a bare clone per source and resolves refs to commit hashes."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)

    def cache_path(self, source: str) -> Path:
        return self.cache_dir / slug_for_source(source)

    def ensure_cached(self, source: str) -> Path:
        """Make a bare cache available for ``source``: clone, fetch or (re)build a seed."""
        if is_seed_directory(source):
            return self._ensure_seed(source)
        return self._ensure_clone(source)

    def _ensure_clone(self, source: str) -> Path:
        bare = self.cache_path(source)
        if bare.exists() and (bare / "HEAD").exists():
            run_git(["fetch", "--all", "--prune", "--tags"], cwd=bare)
            return bare
        bare.parent.mkdir(parents=True, exist_ok=True)
        run_git(["clone", "--bare", "--", source, str(bare)])
        return bare

    def _ensure_seed(self, source: str) -> Path:
        """Build a deterministic bare repository from a plain directory."""
        seed_dir = Path(source).expanduser().resolve()
        bare = self.cache_path(source)
        digest = directory_digest(seed_dir)
        marker = bare / SEED_DIGEST_FILE
        if bare.exists() and (bare / "HEAD").is_file():
            if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest:
                return bare
            shutil.rmtree(bare)

        staging = Path(tempfile.mkdtemp(prefix="akbench-seed-"))
        try:
            worktree = staging / "work"
            shutil.copytree(seed_dir, worktree, ignore=shutil.ignore_patterns(".git"))
            run_git(["init", "--quiet", "--initial-branch=main"], cwd=worktree, env=SEED_IDENTITY)
            run_git(["add", "-A"], cwd=worktree, env=SEED_IDENTITY)
            run_git(
                ["commit", "--quiet", "-m", f"akbench seed {digest[:12]}"],
                cwd=worktree,
                env=SEED_IDENTITY,
            )
            bare.parent.mkdir(parents=True, exist_ok=True)
            run_git(["clone", "--bare", "--", str(worktree), str(bare)])
            marker.write_text(digest + "\n", encoding="utf-8")
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return bare

    def resolve_commit(self, bare: Path, ref: str) -> str:
        """Resolve a branch, tag, ``HEAD`` or commit to a full commit hash."""
        try:
            return run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=bare)
        except WorkspaceError as exc:
            raise WorkspaceError(f"ref {ref!r} not found in {bare}") from exc

    def check(self, source: str, ref: str) -> RepositoryCheck:
        """Report whether the source exists and the ref resolves. Never raises."""
        try:
            bare = self.ensure_cached(source)
            commit = self.resolve_commit(bare, ref)
        except WorkspaceError as exc:
            return RepositoryCheck(ok=False, source=source, ref=ref, detail=str(exc))
        kind = "seed" if is_seed_directory(source) else "git"
        return RepositoryCheck(
            ok=True,
            source=source,
            ref=ref,
            commit=commit,
            detail=f"{kind} · {bare} · commit {commit[:12]}",
        )

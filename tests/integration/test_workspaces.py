"""Workspace Manager and mutation verification, against real git repositories."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from akbench.core.errors import WorkspaceError
from akbench.datasets import RepositoryManager, WorkspaceManager
from akbench.datasets.dataset import Dataset
from akbench.datasets.verification import MutationVerifier, run_hidden_tests

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A real git repository with a branch the cache can pin."""
    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "app").mkdir()
    (repo / "app" / "math.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    _git(["init", "-q", "--initial-branch=main"], cwd=repo)
    _git(["add", "-A"], cwd=repo)
    _git(["-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "base"], cwd=repo)
    return repo


@pytest.fixture
def manager(tmp_path: Path, git_repo: Path) -> WorkspaceManager:
    return WorkspaceManager(RepositoryManager(tmp_path / "cache"), tmp_path / "workspaces")


def test_prepare_is_repeatable(manager: WorkspaceManager, git_repo: Path) -> None:
    dataset = _single_loaded(git_repo)
    a = manager.prepare(dataset.task, "one", apply_mutation=False)
    b = manager.prepare(dataset.task, "two", apply_mutation=False)
    assert a.base_commit == b.base_commit
    assert a.tree == b.tree
    assert a.fingerprint == b.fingerprint


def test_prepare_refuses_to_reuse_an_existing_workspace_id(
    manager: WorkspaceManager, git_repo: Path
) -> None:
    dataset = _single_loaded(git_repo)
    manager.prepare(dataset.task, "same", apply_mutation=False)
    with pytest.raises(WorkspaceError, match="already exists"):
        manager.prepare(dataset.task, "same", apply_mutation=False)


def test_prepare_records_the_pinned_commit(manager: WorkspaceManager, git_repo: Path) -> None:
    dataset = _single_loaded(git_repo)
    prepared = manager.prepare(dataset.task, "rec", apply_mutation=False)
    assert len(prepared.base_commit) == 40
    assert prepared.commit == prepared.base_commit
    assert (prepared.path / "app" / "math.py").is_file()


def test_cleanup_removes_workspace_and_registration(
    manager: WorkspaceManager, git_repo: Path, tmp_path: Path
) -> None:
    dataset = _single_loaded(git_repo)
    prepared = manager.prepare(dataset.task, "gone", apply_mutation=False)
    manager.cleanup(prepared.path)
    assert not prepared.path.exists()
    # a second cleanup is a no-op, not an error
    manager.cleanup(prepared.path)


def test_hidden_tests_are_copied_in_and_removed(
    manager: WorkspaceManager, git_repo: Path, tmp_path: Path
) -> None:
    dataset = _single_loaded(git_repo)
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_hidden.py").write_text(
        "def test_ok():\n    from app.math import add\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    prepared = manager.prepare(dataset.task, "ht", apply_mutation=False)
    run = run_hidden_tests(prepared.path, hidden)
    assert run.passed is True
    leftovers = [p for p in prepared.path.iterdir() if p.name.startswith(".akbench_hidden_tests")]
    assert leftovers == []


def test_run_hidden_tests_reports_a_failure(
    manager: WorkspaceManager, git_repo: Path, tmp_path: Path
) -> None:
    dataset = _single_loaded(git_repo)
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_hidden.py").write_text(
        "def test_bad():\n    from app.math import add\n    assert add(1, 2) == 4\n",
        encoding="utf-8",
    )
    prepared = manager.prepare(dataset.task, "ht2", apply_mutation=False)
    run = run_hidden_tests(prepared.path, hidden)
    assert run.passed is False
    assert run.exit_code == 1


def _single_task(git_repo: Path):
    """A minimal task descriptor pointing at the fixture repo."""
    from akbench.datasets.task import TaskDescriptor

    return TaskDescriptor(
        id="fixture",
        version="1.0.0",
        task={
            "category": "new_feature",
            "difficulty": "easy",
            "repository": {"source": str(git_repo), "ref": "main"},
            "evaluator": "pytest_evaluator",
        },
    )


def _single_loaded(git_repo: Path):
    """The fixture task wrapped in a LoadedTask for the workspace manager."""
    from akbench.datasets.dataset import LoadedTask

    task = _single_task(git_repo)
    return LoadedTask(task=task, path=Path(git_repo), digest="sha256:fixture")


def test_shipped_wordcount_task_verifies() -> None:
    """The end-to-end proof: the sample task's mutation is detectable."""
    scratch = Path(__file__).resolve().parents[2] / "data" / "test_repos"
    import shutil

    if scratch.exists():
        shutil.rmtree(scratch)
    try:
        manager = WorkspaceManager(
            RepositoryManager(scratch / "repos"), scratch / "workspaces"
        )
        dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
        loaded = dataset.materialize(dataset.require("wordcount-001"))
        result = MutationVerifier(manager).verify(loaded)
        assert result.ok, result.as_dict()
        assert result.verdict.value == "verified"
        assert result.base.passed is True
        assert result.mutated.passed is False
    finally:
        if scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)


def test_verification_detects_an_undetectable_mutation(tmp_path: Path) -> None:
    """A mutation that does not break the hidden tests must be rejected."""
    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "app").mkdir()
    (repo / "app" / "math.py").write_text("def add(a, b):\n    return a + b\n")
    _git(["init", "-q", "--initial-branch=main"], cwd=repo)
    _git(["add", "-A"], cwd=repo)
    _git(["-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "base"], cwd=repo)

    task_dir = tmp_path / "datasets" / "bug_fix" / "tricky"
    (task_dir / "hidden_tests").mkdir(parents=True)
    (task_dir / "hidden_tests" / "test_hidden.py").write_text(
        "def test_ok():\n    from app.math import add\n    assert add(1, 2) == 3\n"
    )
    (task_dir / "mutations").mkdir()
    # A harmless rename-style change: comment only, tests still pass.
    (task_dir / "mutations" / "m.patch").write_text(
        "diff --git a/app/math.py b/app/math.py\n"
        "--- a/app/math.py\n+++ b/app/math.py\n"
        "@@ -1,2 +1,3 @@\n"
        "+# harmless comment\n"
        " def add(a, b):\n"
        "     return a + b\n"
    )
    (task_dir / "description.md").write_text("task")
    from akbench.datasets.task import TaskDescriptor

    task = TaskDescriptor(
        id="tricky",
        version="1.0.0",
        task={
            "category": "bug_fix",
            "difficulty": "easy",
            "repository": {"source": str(repo), "ref": "main"},
            "mutation": {"patch": "mutations/m.patch", "version": "1.0.0"},
            "evaluator": "pytest_evaluator",
        },
    )
    from akbench.datasets.dataset import LoadedTask

    manager = WorkspaceManager(RepositoryManager(tmp_path / "c"), tmp_path / "ws")
    result = MutationVerifier(manager).verify(
        LoadedTask(task=task, path=task_dir, digest="sha256:x")
    )
    assert result.verdict.value == "not_detectable"
    assert result.base.passed is True
    assert result.mutated.passed is True

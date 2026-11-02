"""Prove the large tasks are runnable, detectable, and solvable without leakage."""

import shutil
from pathlib import Path

from akbench.datasets import RepositoryManager, WorkspaceManager
from akbench.datasets.dataset import Dataset
from akbench.datasets.verification import MutationVerifier, run_hidden_tests
from akbench.descriptors import load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE = REPO_ROOT / "tests" / "fixtures" / "streamforge_solution"


def assert_suite(workspace: Path, suite: Path, *, passes: bool = True) -> str:
    result = run_hidden_tests(workspace, suite)
    assert not result.errored, result.output
    assert result.passed is passes, result.output
    return result.output


def test_durable_task_descriptors_validate():
    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    report = dataset.validate(load_registry(REPO_ROOT / "descriptors"))
    assert report.ok, report.as_dict()
    assert dataset.require("streamforge-windows-001").task.difficulty == "expert"
    assert dataset.require("walqueue-recovery-001").task.difficulty == "expert"


def test_streamforge_missing_operators_and_reference_solution(tmp_path):
    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    loaded = dataset.materialize(dataset.require("streamforge-windows-001"))
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    prepared = manager.prepare(loaded.task, "streamforge", task_dir=loaded.path)
    try:
        assert not (prepared.path / "hidden_tests").exists()
        assert not list(prepared.path.rglob("*solution*"))
        assert_suite(prepared.path, prepared.path / "tests")
        output = assert_suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "NotImplementedError" in output
        assert_suite(prepared.path, loaded.path / "public_tests", passes=False)
        for filename in ("windows.py", "reconcile.py", "runtime.py"):
            shutil.copy2(REFERENCE / filename, prepared.path / "src" / "streamforge" / filename)
        assert_suite(prepared.path, prepared.path / "tests")
        assert_suite(prepared.path, loaded.path / "public_tests")
        assert_suite(prepared.path, loaded.path / "hidden_tests")
    finally:
        manager.cleanup(prepared.path)


def test_walqueue_mutation_is_verified_and_seed_tests_stay_green(tmp_path):
    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    loaded = dataset.materialize(dataset.require("walqueue-recovery-001"))
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    verification = MutationVerifier(manager).verify(loaded)
    assert verification.ok, (verification.as_dict(), verification.base, verification.mutated)
    assert verification.verdict.value == "verified"
    for mutated in (False, True):
        prepared = manager.prepare(
            loaded.task, f"walqueue-{mutated}", task_dir=loaded.path, apply_mutation=mutated
        )
        try:
            assert_suite(prepared.path, prepared.path / "tests")
            assert_suite(prepared.path, loaded.path / "public_tests", passes=not mutated)
        finally:
            manager.cleanup(prepared.path)

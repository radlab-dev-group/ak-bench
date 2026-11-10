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

def _repository_suite(workspace: Path) -> None:
    import os
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=str(workspace),
        env={
            **os.environ,
            "PYTHONPATH": str(Path(workspace) / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        text=True,
        capture_output=True,
        timeout=600,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _witness_fails_alone(loaded, workspace: Path, witness: str, parts: Path) -> None:
    import json
    import os
    import subprocess
    import sys

    regression = next(
        item for item in json.loads((parts / "parts.json").read_text()) if item["witness"] == witness
    )
    subprocess.run(
        ["git", "apply", str(parts / regression["patch"])],
        cwd=str(workspace),
        check=True,
        capture_output=True,
        text=True,
    )
    shutil.copytree(loaded.path / "hidden_tests", workspace / "hidden_tests")
    completed = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-k", witness, "hidden_tests",
        ],
        cwd=str(workspace),
        env={
            "PYTHONPATH": str(Path(workspace) / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
        },
        text=True,
        capture_output=True,
        timeout=600,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "FAILED" in completed.stdout and witness in completed.stdout


def test_walqueue_compaction_task_verifies_and_the_seed_suite_survives(tmp_path):
    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    loaded = dataset.materialize(dataset.require("walqueue-compaction-002"))
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    verification = MutationVerifier(manager).verify(loaded)
    assert verification.ok, (verification.as_dict(), verification.base, verification.mutated)
    assert verification.verdict.value == "verified"
    for mutated in (False, True):
        prepared = manager.prepare(
            loaded.task, f"walqueue-compaction-{mutated}", task_dir=loaded.path, apply_mutation=mutated
        )
        try:
            _repository_suite(prepared.path)
            assert_suite(prepared.path, loaded.path / "hidden_tests", passes=not mutated)
            assert_suite(prepared.path, loaded.path / "public_tests", passes=not mutated)
        finally:
            manager.cleanup(prepared.path)


def test_walqueue_compaction_parts_each_break_their_own_witness(tmp_path):
    """The four cooperating regressions are independently detectable: each
    part, applied alone, breaks exactly its named witness."""

    import json

    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    loaded = dataset.materialize(dataset.require("walqueue-compaction-002"))
    parts = loaded.path / "mutations"
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    for item in json.loads((parts / "parts.json").read_text()):
        prepared = manager.prepare(
            loaded.task, f"compaction-{Path(item['patch']).stem}", task_dir=loaded.path, apply_mutation=False
        )
        try:
            _witness_fails_alone(loaded, prepared.path, item["witness"], parts)
        finally:
            manager.cleanup(prepared.path)


def test_walqueue_compaction_mutation_is_the_sum_of_its_parts():
    import json

    parts = REPO_ROOT / "datasets" / "bug_fix" / "walqueue-compaction-002" / "mutations"
    shipped = (parts / "mutation-001.patch").read_text()
    shipped_files = {line.split(" b/", 1)[1] for line in shipped.splitlines() if line.startswith("diff --git ")}
    union = set()
    for item in json.loads((parts / "parts.json").read_text()):
        patch = (parts / item["patch"]).read_text()
        union |= {line.split(" b/", 1)[1] for line in patch.splitlines() if line.startswith("diff --git ")}
        for path in union:
            assert not path.startswith(("traces/", "schedules/", "tools/", "tests/", "docs/")), path
    assert shipped_files == union

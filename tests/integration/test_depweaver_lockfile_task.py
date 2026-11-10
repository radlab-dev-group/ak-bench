"""The depweaver reproducible-lockfile feature task and its coexistence with the bug_fix task.

`depweaver-lockfile-001` declares canonical lockfile forms, proofs of solution
and proof-driven cache invalidation on the shared depweaver seed; the reference
lives outside the seed under `tests/fixtures/depweaver_lockfile_solution/`.
The memory experiment is only worth running if the feature is genuinely
missing on the seed, genuinely complete under the reference, and the sibling
task `depweaver-backtracking-001` still verifies on the same seed.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from akbench.datasets import RepositoryManager, WorkspaceManager
from akbench.datasets.dataset import Dataset
from akbench.datasets.verification import MutationVerifier, run_hidden_tests

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "tests" / "fixtures" / "depweaver_lockfile_solution" / "src" / "depweaver"
REFERENCE_MODULES = ("canonical.py", "proofs.py", "store.py")
SOLVER_MODULES = ("candidates.py", "learning.py", "propagation.py", "trail.py", "resolver.py")


def suite(workspace, tests, *, passes=True):
    result = run_hidden_tests(workspace, tests, timeout_seconds=900)
    assert not result.errored, result.output
    assert result.passed is passes, result.output
    return result.output


def repository_suite(workspace):
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(workspace) / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=str(workspace),
        env=environment,
        text=True,
        capture_output=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def install_reference(workspace: Path) -> None:
    for filename in REFERENCE_MODULES:
        shutil.copy2(REFERENCE / filename, workspace / "src" / "depweaver" / filename)


@pytest.fixture
def resources(tmp_path):
    dataset = Dataset.load(ROOT / "datasets", base_dir=ROOT)
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    return dataset, manager


def test_lockfile_feature_is_missing_on_the_seed_and_complete_under_the_reference(resources):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("depweaver-lockfile-001"))
    prepared = manager.prepare(loaded.task, "lockfile", task_dir=loaded.path)
    try:
        assert not list(prepared.path.rglob("*solution*"))
        assert not (prepared.path / "hidden_tests").exists()
        for filename in ("relock.py", "verify_lock.py"):
            assert (prepared.path / "tools" / filename).exists()
        assert (prepared.path / "docs" / "lockfile-canonical-form.md").exists()
        assert (prepared.path / "CONTRIBUTING.md").exists()
        assert "proof" not in (prepared.path / "README.md").read_text().lower()
        repository_suite(prepared.path)
        output = suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "NotImplementedError" in output
        output = suite(prepared.path, loaded.path / "public_tests", passes=False)
        assert "NotImplementedError" in output
        install_reference(prepared.path)
        repository_suite(prepared.path)
        suite(prepared.path, loaded.path / "public_tests")
        suite(prepared.path, loaded.path / "hidden_tests")
    finally:
        manager.cleanup(prepared.path)


def test_reference_does_not_touch_the_solver_and_verification_is_offline():
    seed = ROOT / "datasets" / "_sources" / "depweaver" / "src" / "depweaver"
    for filename in REFERENCE_MODULES:
        assert (REFERENCE / filename).exists(), filename
    for filename in SOLVER_MODULES:
        assert not (REFERENCE / filename).exists(), filename
    proofs = (REFERENCE / "proofs.py").read_text()
    canonical = (REFERENCE / "canonical.py").read_text()
    for module in ("resolver", "propagation", "candidates", "learning", "trail"):
        assert f"from .{module}" not in proofs and f"import {module}" not in proofs
        assert f"from .{module}" not in canonical
    # The seed stubs declare the same surface the reference implements.
    for filename in ("canonical.py", "proofs.py"):
        stub = (seed / filename).read_text()
        assert "NotImplementedError" in stub
        for name in _definitions((REFERENCE / filename).read_text()):
            if not name.startswith("_") and name not in {"Context", "Row"}:
                assert name in _definitions(stub), (filename, name)
    store_stub = (seed / "store.py").read_text()
    for method in ("remember", "recall", "invalidate", "cached", "resolution_path"):
        assert f"def {method}(" in store_stub, method


def _definitions(source: str) -> set[str]:
    """Top-level function and class names of a module."""

    names = set()
    for line in source.splitlines():
        for prefix in ("def ", "class "):
            if line.startswith(prefix):
                names.add(line[len(prefix) :].split("(")[0].split(":")[0])
    return names


def test_sibling_backtracking_task_still_verifies_on_the_shared_seed(resources):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("depweaver-backtracking-001"))
    result = MutationVerifier(manager).verify(loaded)
    assert result.ok, (result.as_dict(), result.base, result.mutated)
    assert result.verdict.value == "verified"
    prepared = manager.prepare(loaded.task, "resolver-mutated", task_dir=loaded.path, apply_mutation=True)
    try:
        repository_suite(prepared.path)
        suite(prepared.path, loaded.path / "public_tests", passes=False)
    finally:
        manager.cleanup(prepared.path)

"""The atlas sharded-store family: the five tasks and the rules between them.

`atlas-drift-001` is the learning task of a family whose twins each hide one
of the same five regressions in a different module, and `atlas-lineage-001`
implements a declared feature of the same store. The memory experiment that
joins them (`configs/experiments/knowledge-replay-atlas.yaml`) is only worth
running if these facts hold, so they are asserted here: every part of the
learning task is independently detectable, every twin is verified and leaves
the repository suite green, and the lineage feature is genuinely missing on
the seed and genuinely complete under the isolated reference.
"""

import json
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
ATLAS_LINEAGE_REFERENCE = ROOT / "tests" / "fixtures" / "atlas_lineage_solution"
DRIFT_FAMILY = ROOT / "datasets" / "bug_fix"
LEARNING_PARTS = DRIFT_FAMILY / "atlas-drift-001" / "mutations"
TWINS = ("atlas-drift-002", "atlas-drift-003", "atlas-drift-004")
LEARNING_REGRESSIONS = json.loads((LEARNING_PARTS / "parts.json").read_text())


def suite(workspace, tests, *, passes=True):
    result = run_hidden_tests(workspace, tests)
    assert not result.errored, result.output
    assert result.passed is passes, result.output
    return result.output


def repository_suite(workspace):
    """Run the store's own suite where it lives.

    The suite drives `tools/parity.py` from the repository root, so it runs in
    place rather than through the staging copy `run_hidden_tests` makes.
    """

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


@pytest.fixture
def resources(tmp_path):
    dataset = Dataset.load(ROOT / "datasets", base_dir=ROOT)
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    return dataset, manager


@pytest.mark.parametrize(
    "regression", LEARNING_REGRESSIONS, ids=lambda item: Path(item["patch"]).stem
)
def test_each_learning_regression_is_independently_detectable(resources, regression):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("atlas-drift-001"))
    prepared = manager.prepare(
        loaded.task, "learning-part", task_dir=loaded.path, apply_mutation=False
    )
    try:
        subprocess.run(
            ["git", "apply", str(LEARNING_PARTS / regression["patch"])],
            cwd=prepared.path,
            check=True,
            capture_output=True,
            text=True,
        )
        environment = {
            **os.environ,
            "PYTHONPATH": str(prepared.path / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                str(loaded.path / "hidden_tests"),
                "-k",
                regression["witness"],
            ],
            cwd=prepared.path,
            env=environment,
            text=True,
            capture_output=True,
            timeout=120,
        )
        assert completed.returncode == 1, completed.stdout + completed.stderr
        assert "FAILED" in completed.stdout and regression["witness"] in completed.stdout, (
            completed.stdout + completed.stderr
        )
    finally:
        manager.cleanup(prepared.path)


@pytest.mark.parametrize("task_id", TWINS)
def test_each_twin_is_verified_and_its_seed_suite_survives(resources, task_id):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(task_id))
    result = MutationVerifier(manager).verify(loaded)
    assert result.ok, (result.as_dict(), result.base, result.mutated)
    assert result.verdict.value == "verified"
    for mutated in (False, True):
        prepared = manager.prepare(
            loaded.task, f"twin-{mutated}", task_dir=loaded.path, apply_mutation=mutated
        )
        try:
            repository_suite(prepared.path)
            suite(prepared.path, loaded.path / "hidden_tests", passes=not mutated)
            suite(prepared.path, loaded.path / "public_tests", passes=not mutated)
        finally:
            manager.cleanup(prepared.path)


def test_the_twins_hide_their_defects_in_different_modules():
    """The transfer must be a transfer: no twin shares a module with another.

    The learning task's five parts name the five modules the family spreads
    over. A twin that regressed the module of the learning task would be an
    exact replay wearing a different name, and the experiment would measure
    recall while it claimed transfer.
    """

    def touched(task_dir: Path) -> set[str]:
        patch = (task_dir / "mutations" / "mutation-001.patch").read_text()
        return {
            line.split(" b/", 1)[1]
            for line in patch.splitlines()
            if line.startswith("diff --git ")
        }

    learning = touched(DRIFT_FAMILY / "atlas-drift-001")
    assert len(learning) == 5, learning
    seen: set[str] = set()
    for task_id in TWINS:
        modules = touched(DRIFT_FAMILY / task_id)
        assert len(modules) == 1, (task_id, modules)
        assert not (seen & modules), (task_id, sorted(seen & modules))
        seen |= modules
    # The twins are a subset of the learning task's families, so a recipe for
    # the principle exists; they are not the learning task's own modules.
    assert len(seen) == 3, seen


def test_atlas_lineage_is_missing_on_the_seed_and_complete_under_the_reference(resources):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("atlas-lineage-001"))
    prepared = manager.prepare(loaded.task, "lineage", task_dir=loaded.path)
    try:
        assert not list(prepared.path.rglob("*solution*"))
        assert not (prepared.path / "hidden_tests").exists()
        repository_suite(prepared.path)
        output = suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "NotImplementedError" in output
        suite(prepared.path, loaded.path / "public_tests", passes=False)
        shutil.copy2(
            ATLAS_LINEAGE_REFERENCE / "lineage.py",
            prepared.path / "src" / "atlas" / "lineage.py",
        )
        repository_suite(prepared.path)
        suite(prepared.path, loaded.path / "public_tests")
        suite(prepared.path, loaded.path / "hidden_tests")
    finally:
        manager.cleanup(prepared.path)

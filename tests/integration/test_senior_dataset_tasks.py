"""Compiler solvability and independent proofs for all eight resolver defects."""

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
REFERENCE = ROOT / "tests" / "fixtures" / "typeweave_solution"
PARTS = ROOT / "datasets" / "bug_fix" / "depweaver-backtracking-001" / "mutations"
REGRESSIONS = json.loads((PARTS / "parts.json").read_text())


def suite(workspace, tests, *, passes=True):
    result = run_hidden_tests(workspace, tests)
    assert not result.errored, result.output
    assert result.passed is passes, result.output
    return result.output


@pytest.fixture
def resources(tmp_path):
    dataset = Dataset.load(ROOT / "datasets", base_dir=ROOT)
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    return dataset, manager


def test_typeweave_is_missing_but_reference_is_complete_and_isolated(resources):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("typeweave-inference-001"))
    prepared = manager.prepare(loaded.task, "compiler", task_dir=loaded.path)
    try:
        assert not list(prepared.path.rglob("*solution*"))
        assert not (prepared.path / "hidden_tests").exists()
        suite(prepared.path, prepared.path / "tests")
        output = suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "NotImplementedError" in output
        suite(prepared.path, loaded.path / "public_tests", passes=False)
        for filename in (
            "unification.py",
            "inference.py",
            "coverage.py",
            "declarations.py",
            "interfaces.py",
        ):
            shutil.copy2(REFERENCE / filename, prepared.path / "src" / "typeweave" / filename)
        suite(prepared.path, prepared.path / "tests")
        suite(prepared.path, loaded.path / "public_tests")
        suite(prepared.path, loaded.path / "hidden_tests")
    finally:
        manager.cleanup(prepared.path)


def test_depweaver_combined_mutation_is_verified_and_seed_suite_survives(resources):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("depweaver-backtracking-001"))
    result = MutationVerifier(manager).verify(loaded)
    assert result.ok, (result.as_dict(), result.base, result.mutated)
    assert result.verdict.value == "verified"
    for mutated in (False, True):
        prepared = manager.prepare(
            loaded.task, f"resolver-{mutated}", task_dir=loaded.path, apply_mutation=mutated
        )
        try:
            suite(prepared.path, prepared.path / "tests")
            suite(prepared.path, loaded.path / "public_tests", passes=not mutated)
        finally:
            manager.cleanup(prepared.path)


@pytest.mark.parametrize("regression", REGRESSIONS, ids=lambda item: Path(item["patch"]).stem)
def test_each_resolver_regression_is_independently_detectable(resources, regression):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("depweaver-backtracking-001"))
    prepared = manager.prepare(
        loaded.task, "single-regression", task_dir=loaded.path, apply_mutation=False
    )
    try:
        subprocess.run(
            ["git", "apply", str(PARTS / regression["patch"])],
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
            timeout=60,
        )
        assert completed.returncode == 1, completed.stdout + completed.stderr
        assert "FAILED" in completed.stdout and regression["witness"] in completed.stdout, (
            completed.stdout + completed.stderr
        )
    finally:
        manager.cleanup(prepared.path)

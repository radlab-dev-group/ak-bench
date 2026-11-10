"""The atlas quorum family: a learning task of two antagonistic pairs and its three twins.

`atlas-quorum-001` hides four regressions in two pairs — the write quorum and
the convergence pass over a retiring replica; read repair and the lease book
over a version — such that the naive fix of either half of a pair reproduces
the other half's failure. `atlas-quorum-002` repeats one of them on another
branch of the same module (exact signature), `atlas-quorum-003` breaks the
same invariant in a module the learning task did not touch (related
transfer), and `atlas-quorum-004` reproduces a learning signature from a
different cause in yet another module (negative transfer). The memory
experiment that joins them is only worth running if those facts hold, so they
are asserted here.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from akbench.datasets import RepositoryManager, WorkspaceManager
from akbench.datasets.dataset import Dataset
from akbench.datasets.verification import MutationVerifier, run_hidden_tests

ROOT = Path(__file__).resolve().parents[2]
FAMILY = ROOT / "datasets" / "bug_fix"
LEARNING = "atlas-quorum-001"
LEARNING_PARTS = FAMILY / LEARNING / "mutations"
LEARNING_REGRESSIONS = json.loads((LEARNING_PARTS / "parts.json").read_text())
TWINS = ("atlas-quorum-002", "atlas-quorum-003", "atlas-quorum-004")
DRIFT_FAMILY = ("atlas-drift-001", "atlas-drift-002", "atlas-drift-003", "atlas-drift-004")
CLAIMED = {
    LEARNING: {
        "src/atlas/replication.py",
        "src/atlas/antientropy.py",
        "src/atlas/repair.py",
        "src/atlas/fencing.py",
    },
    "atlas-quorum-002": {"src/atlas/replication.py"},
    "atlas-quorum-003": {"src/atlas/rebalance.py"},
    "atlas-quorum-004": {"src/atlas/vclock.py"},
}


def suite(workspace, tests, *, passes=True, keyword=None):
    result = run_hidden_tests(workspace, tests)
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


def pytest_in(workspace, tests, *, keyword=None):
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(workspace) / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tests)]
    if keyword:
        command += ["-k", keyword]
    return subprocess.run(
        command, cwd=str(workspace), env=environment, text=True, capture_output=True, timeout=120
    )


def touched(patch_text: str) -> set[str]:
    return {
        line.split(" b/", 1)[1] for line in patch_text.splitlines() if line.startswith("diff --git ")
    }


def changed_lines(patch_text: str) -> dict[str, set[int]]:
    """The base-side line numbers each hunk of ``patch_text`` removes or replaces."""

    lines: dict[str, set[int]] = {}
    current = None
    cursor = 0
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            current = line.split(" b/", 1)[1]
            lines.setdefault(current, set())
        elif line.startswith("@@"):
            cursor = int(re.match(r"@@ -(\d+)", line).group(1))
        elif current is None or line.startswith(("---", "+++")):
            continue
        elif line.startswith("-"):
            lines[current].add(cursor)
            cursor += 1
        elif line.startswith("+"):
            lines[current].add(cursor)
        else:
            cursor += 1
    return lines


def patch_of(task_id: str) -> str:
    return (FAMILY / task_id / "mutations" / "mutation-001.patch").read_text()


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
    loaded = dataset.materialize(dataset.require(LEARNING))
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
        completed = pytest_in(prepared.path, loaded.path / "hidden_tests", keyword=regression["witness"])
        assert completed.returncode == 1, completed.stdout + completed.stderr
        assert "FAILED" in completed.stdout and regression["witness"] in completed.stdout, (
            completed.stdout + completed.stderr
        )
        repository_suite(prepared.path)
    finally:
        manager.cleanup(prepared.path)


def test_the_learning_mutation_is_the_sum_of_its_parts_and_keeps_the_seed_suite_green(resources):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(LEARNING))
    combined = patch_of(LEARNING)
    assert touched(combined) == CLAIMED[LEARNING]
    parts = set()
    for regression in LEARNING_REGRESSIONS:
        parts |= touched((LEARNING_PARTS / regression["patch"]).read_text())
    assert parts == CLAIMED[LEARNING]
    for mutated in (False, True):
        prepared = manager.prepare(
            loaded.task, f"learning-{mutated}", task_dir=loaded.path, apply_mutation=mutated
        )
        try:
            repository_suite(prepared.path)
            suite(prepared.path, loaded.path / "hidden_tests", passes=not mutated)
            suite(prepared.path, loaded.path / "public_tests", passes=not mutated)
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


def test_every_patch_touches_the_files_it_claims():
    for task_id, claimed in CLAIMED.items():
        assert touched(patch_of(task_id)) == claimed, task_id


def test_the_twins_do_not_overlap_each_other_or_the_drift_family():
    """A twin must not share a changed line with another twin or with any drift task."""

    footprints = {task_id: changed_lines(patch_of(task_id)) for task_id in TWINS + DRIFT_FAMILY}
    for index, left in enumerate(TWINS):
        for right in (TWINS + DRIFT_FAMILY)[index + 1 :]:
            if left == right:
                continue
            for path, lines in footprints[left].items():
                shared = lines & footprints[right].get(path, set())
                assert not shared, (left, right, path, sorted(shared))


def test_the_twins_keep_their_roles_relative_to_the_learning_task():
    """Exact twin: same module as a learning part. Related: another module. Negative: another module."""

    learning = CLAIMED[LEARNING]
    assert CLAIMED["atlas-quorum-002"] <= learning
    assert not (CLAIMED["atlas-quorum-003"] & learning)
    assert not (CLAIMED["atlas-quorum-004"] & learning)
    assert not (CLAIMED["atlas-quorum-003"] & CLAIMED["atlas-quorum-004"])


def test_the_negative_twin_shares_its_failure_signature_with_a_learning_part(resources):
    """The convergence error of the vclock twin reads exactly like the one of learning part 02."""

    dataset, manager = resources
    signature = re.compile(r"ConvergenceError: shard \d+ did not converge for epoch \d+")

    learning = dataset.materialize(dataset.require(LEARNING))
    prepared = manager.prepare(learning.task, "signature-learning", task_dir=learning.path, apply_mutation=False)
    try:
        part = next(item for item in LEARNING_REGRESSIONS if "converge" in item["patch"])
        subprocess.run(
            ["git", "apply", str(LEARNING_PARTS / part["patch"])],
            cwd=prepared.path, check=True, capture_output=True, text=True,
        )
        completed = pytest_in(prepared.path, learning.path / "hidden_tests", keyword=part["witness"])
        assert completed.returncode == 1
        learning_signature = signature.search(completed.stdout)
        assert learning_signature, completed.stdout
    finally:
        manager.cleanup(prepared.path)

    negative = dataset.materialize(dataset.require("atlas-quorum-004"))
    prepared = manager.prepare(negative.task, "signature-negative", task_dir=negative.path, apply_mutation=True)
    try:
        completed = pytest_in(prepared.path, negative.path / "hidden_tests")
        assert completed.returncode == 1
        negative_signature = signature.search(completed.stdout)
        assert negative_signature, completed.stdout
        assert "draining" not in patch_of("atlas-quorum-004")
    finally:
        manager.cleanup(prepared.path)

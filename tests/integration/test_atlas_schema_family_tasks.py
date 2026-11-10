"""The atlas schema-evolution family: two new_feature tasks and the rules between them.

`atlas-schema-001` implements the row half of SPEC.md section 10 (upgrade on
read, dual-write, downgrade, registration) and performs the schema procedure
(regenerate, lock, goldens); `atlas-schema-002` implements the index half
and performs the same procedure for a new index. The memory experiment that
joins them is only worth running if these facts hold, so they are asserted
here: the seed suite is green and its tables are locked; each task's hidden
and public tests are genuinely failing on the seed and genuinely complete
under its isolated reference; and the two references are not interchangeable.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from akbench.datasets import RepositoryManager, WorkspaceManager
from akbench.datasets.dataset import Dataset
from akbench.datasets.verification import run_hidden_tests

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "datasets" / "_sources" / "atlas"
REFERENCES = ROOT / "tests" / "fixtures" / "atlas_schema_solution"
TASKS = {"atlas-schema-001": REFERENCES / "001", "atlas-schema-002": REFERENCES / "002"}


def suite(workspace, tests, *, passes=True):
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


def tool(workspace, name, *arguments):
    return subprocess.run(
        [sys.executable, str(Path(workspace) / "tools" / name), *arguments],
        cwd=str(workspace),
        env={**os.environ, "PYTHONPATH": str(Path(workspace) / "src")},
        text=True,
        capture_output=True,
        timeout=120,
    )


def apply_reference(workspace: Path, reference: Path) -> None:
    shutil.copytree(reference, workspace, dirs_exist_ok=True)


@pytest.fixture
def resources(tmp_path):
    dataset = Dataset.load(ROOT / "datasets", base_dir=ROOT)
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    return dataset, manager


def test_the_seed_tables_are_locked_and_the_goldens_are_declared_not_verified():
    checked = tool(SEED, "gen_tables.py", "--check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    goldens = tool(SEED, "verify_goldens.py")
    assert goldens.returncode == 1
    assert "NotImplemented(records-v1)" in goldens.stdout
    assert "NotImplemented(index-by_writer)" in goldens.stdout
    assert "GoldenMismatch" not in goldens.stdout
    # the procedure is stated in the guide and nowhere in the README
    guide = (SEED / "docs" / "schema-evolution.md").read_text(encoding="utf-8")
    readme = (SEED / "README.md").read_text(encoding="utf-8")
    assert "gen_tables.py --lock" in guide and "verify_goldens.py" in guide and "MANIFEST" in guide
    assert "gen_tables" not in readme and "MANIFEST" not in readme
    assert "## 10. Schema evolution" in (SEED / "SPEC.md").read_text(encoding="utf-8")
    for number in ("0010", "0011", "0012", "0013"):
        assert list((SEED / "docs" / "adr").glob(f"ADR-{number}-*.md")), number


@pytest.mark.parametrize("task_id", sorted(TASKS))
def test_each_task_is_missing_on_the_seed_and_complete_under_its_reference(resources, task_id):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(task_id))
    prepared = manager.prepare(loaded.task, "schema", task_dir=loaded.path)
    try:
        assert not list(prepared.path.rglob("*solution*"))
        assert not (prepared.path / "hidden_tests").exists()
        repository_suite(prepared.path)
        output = suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "NotImplementedError" in output
        suite(prepared.path, loaded.path / "public_tests", passes=False)
        apply_reference(prepared.path, TASKS[task_id])
        checked = tool(prepared.path, "gen_tables.py", "--check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        repository_suite(prepared.path)
        suite(prepared.path, loaded.path / "public_tests")
        suite(prepared.path, loaded.path / "hidden_tests")
    finally:
        manager.cleanup(prepared.path)


@pytest.mark.parametrize(
    ("task_id", "other"),
    [("atlas-schema-001", "atlas-schema-002"), ("atlas-schema-002", "atlas-schema-001")],
)
def test_the_reference_of_one_task_does_not_satisfy_the_other(resources, task_id, other):
    """The twin is a transfer of the procedure, not of the code."""

    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(task_id))
    prepared = manager.prepare(loaded.task, "cross", task_dir=loaded.path)
    try:
        apply_reference(prepared.path, TASKS[other])
        output = suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "NotImplementedError" in output or "AssertionError" in output
    finally:
        manager.cleanup(prepared.path)


def test_the_hidden_fixtures_are_large_and_the_dead_end_is_the_same_error(resources):
    """A change to the codec's canonical form passes the public tests and fails
    the hidden round trip with ``CodecMismatch(records-v1, ...)`` — the error an
    unfinished downgrade produces."""

    fixtures = ROOT / "datasets" / "new_feature" / "atlas-schema-001" / "hidden_tests" / "fixtures"
    total = sum(path.stat().st_size for path in fixtures.rglob("*") if path.is_file())
    assert total > 300 * 1024, total
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("atlas-schema-001"))
    prepared = manager.prepare(loaded.task, "deadend", task_dir=loaded.path)
    try:
        apply_reference(prepared.path, TASKS["atlas-schema-001"])
        codec = prepared.path / "src" / "atlas" / "codec.py"
        source = codec.read_text(encoding="utf-8")
        assert "ensure_ascii=False" in source
        codec.write_text(source.replace("ensure_ascii=False", "ensure_ascii=True"), encoding="utf-8")
        suite(prepared.path, loaded.path / "public_tests")
        output = suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "CodecMismatch(records-v1, expected=" in output
        assert "GoldenMismatch(records-v1, expected=" in output
    finally:
        manager.cleanup(prepared.path)

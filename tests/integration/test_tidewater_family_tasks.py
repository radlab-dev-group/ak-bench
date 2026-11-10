"""The tidewater election family: a learning task of five regressions and its two twins.

`tidewater-election-001` hides five regressions in two antagonistic pairs and
a single — a candidate that answers a rival in its own term, a candidate that
counts an answer from a closed term, a granted vote that replies before it is
durable, a ``sync`` that no longer makes the recorded vote durable, and an
election that inherits the tally of the one that failed. All five end in the
same ``election_safety`` line. `tidewater-election-002` breaks the same
decision — a majority of the configuration — in the module the learning patch
never touched (related transfer), and `tidewater-election-003` reproduces the
learning signature from a different cause: legal ballots, wrong set
(negative transfer). The memory experiment that joins them is only worth
running if those facts hold, so they are asserted here.
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
SEED = ROOT / "datasets" / "_sources" / "tidewater"
LEARNING = "tidewater-election-001"
LEARNING_PARTS = FAMILY / LEARNING / "mutations"
LEARNING_REGRESSIONS = json.loads((LEARNING_PARTS / "parts.json").read_text())
TWINS = ("tidewater-election-002", "tidewater-election-003")
DURABILITY_SINGLE = "parts/05-sync-drops-the-vote.patch"
CLAIMED = {
    LEARNING: {"src/tidewater/node.py", "src/tidewater/storage.py"},
    "tidewater-election-002": {"src/tidewater/membership.py"},
    "tidewater-election-003": {"src/tidewater/node.py"},
}
TWO_LEADERS = re.compile(r"election_safety(?: at tick \d+)?: term \d+ has two leaders: (\S+) and (\S+)")


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
        timeout=600,
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
        command, cwd=str(workspace), env=environment, text=True, capture_output=True, timeout=300
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


def test_the_learning_witnesses_are_named_and_distinct():
    names = [item["witness"] for item in LEARNING_REGRESSIONS]
    assert len(names) == len(set(names)) == 5
    source = (FAMILY / LEARNING / "hidden_tests" / "test_election_hidden.py").read_text(encoding="utf-8")
    for name in names:
        assert f"def {name}(" in source, name


def test_the_seed_is_documented_to_the_hierarchy_the_tasks_point_at():
    """The decisive rules live in a decision record and an incident note, and
    the README is approximate where they are concerned."""

    assert list((SEED / "docs" / "adr").glob("ADR-0013-*.md")), "the one-ballot-per-term record"
    assert list((SEED / "docs" / "incidents").glob("INC-0009-*.md")), "two leaders, no restart"
    inc_0002 = (SEED / "docs" / "incidents" / "INC-0002-two-leaders-in-one-term-after-restart.md")
    inc_0008 = (SEED / "docs" / "incidents" / "INC-0008-minority-side-kept-committing-during-partition.md")
    assert "the machine an answer arrived through" in inc_0008.read_text(encoding="utf-8")
    assert "two leaders" in inc_0002.read_text(encoding="utf-8")
    readme = (SEED / "README.md").read_text(encoding="utf-8")
    spec = (SEED / "SPEC.md").read_text(encoding="utf-8")
    assert "one ballot per term" not in readme.lower()
    assert "size // 2 + 1" in spec
    assert "2.6 **Granting a vote.**" in spec


@pytest.mark.parametrize(
    "regression", LEARNING_REGRESSIONS, ids=lambda item: Path(item["patch"]).stem
)
def test_each_learning_regression_is_independently_detectable(resources, regression):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(LEARNING))
    prepared = manager.prepare(loaded.task, "learning-part", task_dir=loaded.path, apply_mutation=False)
    try:
        subprocess.run(
            ["git", "apply", str(LEARNING_PARTS / regression["patch"])],
            cwd=prepared.path, check=True, capture_output=True, text=True,
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


def test_the_learning_regressions_end_in_the_line_the_family_is_named_for(resources):
    """The four election regressions all end in ``term N has two leaders``,
    which is what makes an antagonistic pair a pair rather than two unrelated
    bugs, and what makes one failure signature enough to recognise five
    defects; the single is a durability defect and fails on its own line."""

    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(LEARNING))
    seen = {}
    for regression in LEARNING_REGRESSIONS:
        prepared = manager.prepare(loaded.task, "pair", task_dir=loaded.path, apply_mutation=False)
        try:
            subprocess.run(
                ["git", "apply", str(LEARNING_PARTS / regression["patch"])],
                cwd=prepared.path, check=True, capture_output=True, text=True,
            )
            completed = pytest_in(prepared.path, loaded.path / "hidden_tests", keyword=regression["witness"])
            assert completed.returncode == 1, completed.stdout
            if regression["patch"] == DURABILITY_SINGLE:
                assert "the vote rode with the term" in completed.stdout, (
                    regression["patch"], completed.stdout[-3000:]
                )
            else:
                assert TWO_LEADERS.search(completed.stdout), (regression["patch"], completed.stdout[-3000:])
            seen[Path(regression["patch"]).stem] = completed.stdout
        finally:
            manager.cleanup(prepared.path)
    assert len(seen) == 5


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


def test_every_patch_touches_the_files_it_claims_and_no_artefact():
    for task_id, claimed in CLAIMED.items():
        assert touched(patch_of(task_id)) == claimed, task_id
    for task_id in [LEARNING, *TWINS]:
        for path in touched(patch_of(task_id)):
            assert not path.startswith(("traces/", "schedules/", "tools/", "tests/", "docs/")), path


def test_the_twins_keep_their_roles_relative_to_the_learning_task():
    """Related: another module, same invariant. Negative: the learning
    signature from another cause, on lines the learning patch never touched."""

    learning = CLAIMED[LEARNING]
    assert not (CLAIMED["tidewater-election-002"] & learning)
    assert not (CLAIMED["tidewater-election-003"] & CLAIMED["tidewater-election-002"])

    learning_lines: dict[str, set[int]] = {}
    for regression in LEARNING_REGRESSIONS:
        for path, lines in changed_lines((LEARNING_PARTS / regression["patch"]).read_text()).items():
            learning_lines.setdefault(path, set()).update(lines)
    for twin in TWINS:
        for path, lines in changed_lines(patch_of(twin)).items():
            assert not (lines & learning_lines.get(path, set())), (twin, path, sorted(lines))


def test_the_negative_twin_shares_its_failure_signature_with_the_learning_task(resources):
    """The negative twin's safety witness fails with the learning family's own
    line — ``term N has two leaders: A and B`` — while none of the changed
    lines carry the ballot, term or durability vocabulary the learning recipe
    is written against, which is what makes the remembered recipe a trap."""

    negative_patch = patch_of("tidewater-election-003")
    changed = [line[1:] for line in negative_patch.splitlines()
               if line.startswith(("-", "+")) and not line.startswith(("---", "+++"))]
    changed_text = "\n".join(changed)
    assert "sync" not in changed_text, "the twin's fix must not touch the durability line"
    assert "current_term" not in changed_text, "the twin's fix must not touch the term bookkeeping"
    assert "votes" in changed_text

    dataset, manager = resources
    learning = dataset.materialize(dataset.require(LEARNING))
    negative = dataset.materialize(dataset.require("tidewater-election-003"))
    outputs = {}
    for loaded, mutated, key in ((learning, False, "learning"), (negative, True, "negative")):
        prepared = manager.prepare(loaded.task, "signature", task_dir=loaded.path, apply_mutation=mutated)
        try:
            if key == "learning":
                part = next(item for item in LEARNING_REGRESSIONS if "rival" in item["patch"])
                subprocess.run(
                    ["git", "apply", str(LEARNING_PARTS / part["patch"])],
                    cwd=prepared.path, check=True, capture_output=True, text=True,
                )
            completed = pytest_in(prepared.path, loaded.path / "hidden_tests")
            assert completed.returncode == 1, completed.stdout
            assert TWO_LEADERS.search(completed.stdout), (key, completed.stdout[-3000:])
            outputs[key] = completed.stdout
        finally:
            manager.cleanup(prepared.path)
    assert len(outputs) == 2

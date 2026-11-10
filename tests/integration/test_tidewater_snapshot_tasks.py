"""The tidewater snapshot pair: a new feature and the transfer of its procedure.

`tidewater-snapshot-001` implements the node half of ``SPEC.md`` 6 — take the
record at ``last_applied``, keep the boundary term, restart from the snapshot —
and lands the corpus entry the new digest-visible event needs.
`tidewater-snapshot-002` is the related transfer: the other half of the same
section (6.4, 6.5 and the crash mid-transfer), which has to be landed with the
same procedure and a corpus entry of its own. The facts the memory experiment
depends on are asserted here: the seed really is a stub, the rules the tasks
need really live in the documentation and not in the README, each task's tests
fail on the seed and pass under the isolated reference, the corpus grows by the
tool and not by hand, and the reference of the earlier task does not finish the
later one.
"""

import hashlib
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
SEED = ROOT / "datasets" / "_sources" / "tidewater"
REFERENCES = ROOT / "tests" / "fixtures" / "tidewater_snapshot_solution"
TASKS = {
    "tidewater-snapshot-001": REFERENCES / "001",
    "tidewater-snapshot-002": REFERENCES / "002",
}
ENTRY = {"tidewater-snapshot-001": "compaction-quiet", "tidewater-snapshot-002": "compaction-catchup"}
STUBS = [
    "snapshot.take_snapshot(node, snapshot.SnapshotPolicy(threshold=1))",
    "snapshot.resume_after_restart(node)",
    "snapshot.send_snapshot_chunk(node, 'n2', 0)",
    "snapshot.receive_snapshot_chunk(node, 'n1', message)",
    "snapshot.on_snapshot_ack(node, 'n2', message)",
]


def suite(workspace, tests, *, passes=True):
    result = run_hidden_tests(workspace, tests)
    assert not result.errored, result.output
    assert result.passed is passes, result.output
    return result.output


def repository_suite(workspace, *, passes=True):
    completed = python(workspace, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests")
    assert (completed.returncode == 0) is passes, completed.stdout + completed.stderr
    return completed.stdout + completed.stderr


def python(workspace, *arguments, inject_path=True):
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(workspace) / "src") if inject_path else os.environ.get("PYTHONPATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, *[str(argument) for argument in arguments]],
        cwd=str(workspace),
        env=environment,
        text=True,
        capture_output=True,
        timeout=900,
    )


def tool(workspace, name, *arguments):
    return python(workspace, Path(workspace) / "tools" / name, *arguments)


def apply_reference(workspace: Path, reference: Path) -> None:
    shutil.copytree(reference, workspace, dirs_exist_ok=True)


def manifest_lines(workspace: Path) -> dict[str, str]:
    lines = (workspace / "schedules" / "MANIFEST").read_text(encoding="utf-8").splitlines()
    return {
        line.split()[1]: line.split()[0]
        for line in lines
        if line.strip() and not line.startswith("#")
    }


@pytest.fixture
def resources(tmp_path):
    dataset = Dataset.load(ROOT / "datasets", base_dir=ROOT)
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    return dataset, manager


def test_the_seed_declares_the_whole_of_section_6_and_implements_none_of_it():
    """Nothing of this feature was committed to the seed, and the tools are
    green before anybody touches them."""

    assert tool(SEED, "gen_schedules.py", "--check").returncode == 0
    assert tool(SEED, "reference_traces.py", "--check", "--only", "baseline-steady").returncode == 0
    assert len(manifest_lines(SEED)) == 12, "twelve schedules before the feature, one more after each task"

    probe = """
from tidewater import snapshot
from tidewater.clock import NodeClock
from tidewater.errors import FeatureNotImplemented
from tidewater.membership import Configuration
from tidewater.messages import InstallSnapshot
from tidewater.node import Node, NodeOptions
from tidewater.rng import SeedTree
from tidewater.storage import Storage
from tidewater.trace import Trace

tree = SeedTree(3)
node = Node(node_id="n1", config=Configuration.of(("n1",)), storage=Storage("n1", ("n1",)),
            rng=tree.stream("n1", "election"), clock=NodeClock(), trace=Trace(),
            options=NodeOptions(compaction_threshold=4))
message = InstallSnapshot(term=1, leader_id="n2", last_included_index=1, last_included_term=1,
                          offset=0, data=b"x", done=True)
calls = [
    "snapshot.take_snapshot(node, snapshot.SnapshotPolicy(threshold=1))",
    "snapshot.resume_after_restart(node)",
    "snapshot.send_snapshot_chunk(node, 'n2', 0)",
    "snapshot.receive_snapshot_chunk(node, 'n1', message)",
    "snapshot.on_snapshot_ack(node, 'n2', message)",
]
for call in calls:
    try:
        eval(call)
    except FeatureNotImplemented:
        pass
    else:
        raise SystemExit(f"the seed implements {call}")
print("stubbed")
"""
    completed = python(SEED, "-c", probe)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip().endswith("stubbed")
    assert "take_snapshot" in (SEED / "src" / "tidewater" / "snapshot.py").read_text(encoding="utf-8")


def test_the_rules_the_tasks_need_are_written_down_and_the_readme_is_stale():
    """The documentation is the only place the rules are, which is what makes a
    documentation map worth carrying."""

    contributing = (SEED / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "docs/adr" in contributing and "SPEC.md" in contributing and "README.md" in contributing

    runbook = (SEED / "docs" / "runbooks" / "regenerate-traces.md").read_text(encoding="utf-8")
    for step in ("gen_schedules.py --lock", "reference_traces.py", "MANIFEST"):
        assert step in runbook, step

    boundary = (SEED / "docs" / "adr" / "ADR-0006-snapshot-boundary-term.md").read_text(encoding="utf-8")
    transfer = (
        SEED / "docs" / "adr" / "ADR-0011-snapshot-transfer-resumes-from-follower-offset.md"
    ).read_text(encoding="utf-8")
    digests = (SEED / "docs" / "adr" / "ADR-0010-trace-digest-scope.md").read_text(encoding="utf-8")
    assert "base_index" in boundary and "last_included_term" in boundary
    assert "volatile" in transfer and "the follower's offset" in transfer
    assert "digest" in digests and "committed" in digests

    readme = (SEED / "README.md").read_text(encoding="utf-8")
    assert "Compaction is on by default" in readme, "the README is stale about the feature on purpose"
    assert "FeatureNotImplemented" in (SEED / "SPEC.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("task_id", sorted(TASKS))
def test_each_task_is_missing_on_the_seed_and_complete_under_its_reference(resources, task_id):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(task_id))
    prepared = manager.prepare(loaded.task, task_id, task_dir=loaded.path)
    try:
        assert not list(prepared.path.rglob("*solution*"))
        assert not (prepared.path / "hidden_tests").exists()
        repository_suite(prepared.path)

        output = suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "FeatureNotImplemented" in output, output[-3000:]
        suite(prepared.path, loaded.path / "public_tests", passes=False)

        apply_reference(prepared.path, TASKS[task_id])
        assert tool(prepared.path, "gen_schedules.py", "--check").returncode == 0
        assert tool(prepared.path, "reference_traces.py", "--check").returncode == 0
        repository_suite(prepared.path)
        suite(prepared.path, loaded.path / "public_tests")
        suite(prepared.path, loaded.path / "hidden_tests")
    finally:
        manager.cleanup(prepared.path)


@pytest.mark.parametrize("task_id", sorted(TASKS))
def test_the_corpus_entry_of_each_task_is_generated_locked_and_digested(resources, task_id):
    """The deliverable is the artefact tree: a schedule the generator
    produces, a MANIFEST line that locks it, and a digest the trace tool
    wrote. The earlier task's entry is not carried along by the later one."""

    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(task_id))
    prepared = manager.prepare(loaded.task, "corpus", task_dir=loaded.path)
    try:
        apply_reference(prepared.path, TASKS[task_id])
        name = ENTRY[task_id]
        locked = manifest_lines(prepared.path)
        assert f"{name}.json" in locked, sorted(locked)
        path = prepared.path / "schedules" / f"{name}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == locked[f"{name}.json"]
        assert (prepared.path / "traces" / f"{name}.digest").is_file()

        listed = tool(prepared.path, "gen_schedules.py", "--list").stdout
        assert f"{name}:" in listed
        other = ENTRY["tidewater-snapshot-001" if task_id == "tidewater-snapshot-002" else "tidewater-snapshot-002"]
        assert (f"{other}:" in listed) is (task_id == "tidewater-snapshot-002"), (
            "002 builds on 001, so its corpus has both entries; 001 has only its own"
        )
    finally:
        manager.cleanup(prepared.path)


def test_the_reference_of_the_first_task_does_not_finish_the_second(resources):
    """The transfer task is a transfer of the procedure, not of the code: the
    node half alone cannot bring a follower level, and its corpus has no
    catch-up entry."""

    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("tidewater-snapshot-002"))
    prepared = manager.prepare(loaded.task, "cross", task_dir=loaded.path)
    try:
        apply_reference(prepared.path, TASKS["tidewater-snapshot-001"])
        output = suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "FeatureNotImplemented" in output
        assert not (prepared.path / "schedules" / f"{ENTRY['tidewater-snapshot-002']}.json").exists()
    finally:
        manager.cleanup(prepared.path)


def test_the_transfer_reference_also_completes_the_node_task(resources):
    """The pair is a build-up, not an alternative: 6.4 on top of 6.1-6.3 still
    satisfies the acceptance tests of the earlier task."""

    dataset, manager = resources
    loaded = dataset.materialize(dataset.require("tidewater-snapshot-001"))
    prepared = manager.prepare(loaded.task, "cross", task_dir=loaded.path)
    try:
        apply_reference(prepared.path, TASKS["tidewater-snapshot-002"])
        suite(prepared.path, loaded.path / "hidden_tests")
    finally:
        manager.cleanup(prepared.path)


def test_a_reference_moves_the_records_that_describe_the_surface_and_nothing_else(tmp_path):
    """A reference may not smuggle its acceptance tests into the seed: every
    file it touches is the implementation, the tool and corpus entry it was
    asked to generate, or one of the repository records that describe the
    declared surface."""

    allowed = {
        "SPEC.md",
        "schedules/MANIFEST",
        "tools/gen_schedules.py",
        "src/tidewater/node.py",
        "src/tidewater/snapshot.py",
        "src/tidewater/trace.py",
        "tests/test_declared_features.py",
        "tests/test_messages_trace.py",
        "tests/test_tools_cli.py",
    }
    for task_id, reference in TASKS.items():
        name = ENTRY[task_id]
        permitted = allowed | {
            f"schedules/{schedule}.json"
            for schedule in ("compaction-quiet", "compaction-catchup")[: 2 if task_id == "tidewater-snapshot-002" else 1]
        } | {
            f"traces/{schedule}.digest"
            for schedule in ("compaction-quiet", "compaction-catchup")[: 2 if task_id == "tidewater-snapshot-002" else 1]
        }
        shipped = {path.relative_to(reference).as_posix() for path in reference.rglob("*") if path.is_file()}
        assert shipped == permitted, (task_id, sorted(shipped ^ permitted))


def test_a_reference_leaves_the_seed_suite_the_same_size_it_found(resources):
    """The repository suite is green before and after, and the references do
    not add tests to it: they rewrite the three records that call the surface a
    stub."""

    dataset, manager = resources
    for task_id in sorted(TASKS):
        loaded = dataset.materialize(dataset.require(task_id))
        prepared = manager.prepare(loaded.task, "count", task_dir=loaded.path)
        try:
            before = {path.relative_to(prepared.path).as_posix() for path in (prepared.path / "tests").rglob("test_*.py")}
            repository_suite(prepared.path)
            apply_reference(prepared.path, TASKS[task_id])
            after = {path.relative_to(prepared.path).as_posix() for path in (prepared.path / "tests").rglob("test_*.py")}
            assert after == before, (task_id, sorted(after ^ before))
            repository_suite(prepared.path)
        finally:
            manager.cleanup(prepared.path)



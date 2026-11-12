"""Harness for the chaos-schedule synthesis task.

The agent writes chaos/byzantine-partition.json and tests/test_chaos_schedules.py.
The pair has to be green against the simulator as it stands and red against each
of three single-expression mutants of the quorum rules. The mutants are applied
here, to a throwaway copy, and are never shipped inside the repository.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import tidewater

SCHEDULE_REL = Path("chaos/byzantine-partition.json")
TEST_REL = Path("tests/test_chaos_schedules.py")
RUN_TIMEOUT_SECONDS = 900
NEWLINE = chr(10)

MUTANTS: dict[str, tuple[str, str, str]] = {
    "minority-quorum": (
        "src/tidewater/membership.py",
        "        return self.size // 2 + 1",
        "        return self.size // 2 if self.size > 1 else 1",
    ),
    "commit-no-quorum": (
        "src/tidewater/node.py",
        "            if self.config.has_majority(acks):",
        "            if acks:",
    ),
    "stale-term-append": (
        "src/tidewater/node.py",
        "    def _handle_append_entries(self, src: str, msg: AppendEntries) -> None:"
        + NEWLINE
        + "        if msg.term < self.current_term:",
        "    def _handle_append_entries(self, src: str, msg: AppendEntries) -> None:"
        + NEWLINE
        + "        if False:",
    ),
}


def _repo_root() -> Path:
    return Path(tidewater.__file__).resolve().parents[2]


def _load():
    path = _repo_root() / SCHEDULE_REL
    assert path.is_file(), f"missing {SCHEDULE_REL}: write your schedule there"
    return json.loads(path.read_text(encoding="utf-8"))


def _copy(mutant: str | None) -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="chaos-harness-"))
    work = scratch / "repo"
    shutil.copytree(
        _repo_root(), work, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache")
    )
    if mutant is not None:
        relative, old, new = MUTANTS[mutant]
        target = work / relative
        text = target.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"the {mutant} anchor no longer matches {relative}"
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return work


def _run_agent_test(work: Path) -> subprocess.CompletedProcess:
    assert (work / TEST_REL).is_file(), f"missing {TEST_REL}: write your test there"
    environment = {
        **os.environ,
        "PYTHONPATH": str(work / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
            str(work / TEST_REL),
        ],
        cwd=work,
        env=environment,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_SECONDS,
    )


def test_the_agent_test_file_exists():
    assert (_repo_root() / TEST_REL).is_file(), f"write your test in {TEST_REL}"


def test_the_schedule_is_a_schedule_of_the_shape_asked_for():
    from tidewater.schedule import load_schedule

    work = _copy(None)
    schedule = load_schedule(str(work / SCHEDULE_REL))
    schedule.validate()
    kinds = [action.kind for action in schedule.actions]
    assert len(schedule.nodes) >= 3, "the quorum rules are about a majority of several nodes"
    assert schedule.ticks >= 1500, "a run this short cannot hold a partition open and heal it"
    assert kinds.count("partition") >= 3, "the schedule has to cut the cluster apart more than once"
    assert kinds.count("heal") >= 2, "the halves have to meet again for a violation to surface"
    assert "crash" in kinds, "the schedule has to take a node away"
    assert "workload" in kinds or "propose" in kinds, "a schedule that writes nothing loses nothing"
    shutil.rmtree(work.parent, ignore_errors=True)


def test_the_schedule_commits_work_on_the_simulator_as_it_stands():
    from tidewater.cluster import Cluster
    from tidewater.schedule import load_schedule

    work = _copy(None)
    environment = {"PYTHONPATH": str(work / "src"), "PATH": "/usr/bin:/bin", "HOME": str(work)}
    script = (
        "import sys;"
        f"sys.path.insert(0, {str(work / 'src')!r});"
        "from tidewater.cluster import Cluster;"
        "from tidewater.schedule import load_schedule;"
        f"schedule = load_schedule({str(work / SCHEDULE_REL)!r});"
        "result = Cluster(schedule, stop_on_violation=True).run();"
        "print(len(result.commit_indexes), result.ok)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=work,
        env={**environment},
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_SECONDS,
    )
    shutil.rmtree(work.parent, ignore_errors=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    committed, _, ok = completed.stdout.strip().partition(" ")
    assert ok == "True", "the schedule must run clean on the simulator as it stands"
    assert int(committed) > 0, "the schedule committed nothing; it cannot detect the loss of a commit"


def test_the_agent_test_passes_on_the_simulator_as_it_stands():
    work = _copy(None)
    try:
        result = _run_agent_test(work)
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)
    assert result.returncode == 0, (
        "the test has to be green on the repository as it stands:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "no tests ran" not in result.stdout, "the test collected nothing"


@pytest.mark.parametrize("mutant", sorted(MUTANTS))
def test_the_agent_test_fails_on_the_quorum_defects(mutant: str):
    work = _copy(mutant)
    try:
        result = _run_agent_test(work)
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)
    assert result.returncode != 0, (
        f"{mutant} was not detected: the test is green with {MUTANTS[mutant][0]} weakened "
        f"({MUTANTS[mutant][1]!r} -> {MUTANTS[mutant][2]!r})"
    )


def test_the_generated_schedule_corpus_is_untouched():
    root = _repo_root()
    completed = subprocess.run(
        [sys.executable, "tools/gen_schedules.py", "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(root / "src")},
    )
    assert completed.returncode == 0, (
        "schedules/ is generated and locked by MANIFEST; the chaos schedule belongs in chaos/\n"
        f"{completed.stdout}\n{completed.stderr}"
    )

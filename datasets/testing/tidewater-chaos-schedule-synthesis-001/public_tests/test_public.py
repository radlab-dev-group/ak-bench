"""What you can check from your side while you write the schedule.

Run these from the repository root. They cover the shape of the two files and a
clean run; the hidden harness adds the three quorum defects.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "tidewater").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared tidewater workspace")


ROOT = _root()
sys.path.insert(0, str(ROOT / "src"))

from tidewater.cluster import Cluster  # noqa: E402
from tidewater.schedule import load_schedule  # noqa: E402

SCHEDULE = ROOT / "chaos" / "byzantine-partition.json"
TEST = ROOT / "tests" / "test_chaos_schedules.py"


def test_both_deliverables_exist():
    assert SCHEDULE.is_file(), f"write the schedule in {SCHEDULE}"
    assert TEST.is_file(), f"write the test in {TEST}"


def test_the_schedule_validates_and_holds_a_partition_open():
    schedule = load_schedule(str(SCHEDULE))
    schedule.validate()
    kinds = [action.kind for action in schedule.actions]
    assert kinds.count("partition") >= 3
    assert kinds.count("heal") >= 2
    assert "crash" in kinds
    windows = [
        (later.at - action.at)
        for action, later in zip(
            [a for a in schedule.actions if a.kind == "partition"],
            [a for a in schedule.actions if a.kind == "heal"],
        )
    ]
    assert any(window > 2 * schedule.node_options.election_timeout for window in windows), (
        "no partition outlasts an election timeout, so no group can elect on its own "
        "inside it and nothing is lost when the halves heal"
    )


def test_a_clean_run_is_green_and_commits_something():
    schedule = load_schedule(str(SCHEDULE))
    result = Cluster(schedule, stop_on_violation=True).run()
    assert result.ok, f"the schedule is not clean on the simulator as it stands: {result.violation}"
    assert len(result.commit_indexes) > 0, "the schedule commits nothing"

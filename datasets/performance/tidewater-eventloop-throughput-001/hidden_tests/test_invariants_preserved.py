"""The checks stay on, and the twelve traces stay where they are.

Speed bought by not looking is not speed, it is blindness: the monitor exists
because two leaders in one term is a thing that happens
(`docs/incidents/INC-0002`, `docs/incidents/INC-0009`).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

def _workspace_root() -> Path:
    """The root of the checkout under test.

    Hidden tests are copied into the workspace at evaluation time and one
    directory deeper when the dataset validator verifies a mutation, so the
    root is found by walking up to the project marker rather than counting
    directories.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise AssertionError("the checkout under test was not found")


ROOT = _workspace_root()
SCHEDULES = sorted(path.stem for path in (ROOT / "schedules").glob("*.json"))


def _reference(name: str) -> dict:
    fields = {}
    for line in (ROOT / "traces" / f"{name}.digest").read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition(" ")
        fields[key] = value.strip()
    return fields


@pytest.mark.parametrize("name", SCHEDULES)
def test_the_trace_digest_matches_the_reference(name: str):
    from tidewater.cluster import Cluster
    from tidewater.schedule import load_schedule

    result = Cluster(load_schedule(ROOT / "schedules" / f"{name}.json")).run()
    assert result.digest == _reference(name)["trace_digest"], f"{name}: the trace moved"
    assert str(result.events) == _reference(name)["events"], f"{name}: the event count moved"


def test_a_broken_cluster_is_still_reported():
    """Leader completeness, with a follower whose disk does not honour fsync."""

    from tidewater.cluster import Cluster
    from tidewater.invariants import SafetyViolation
    from tidewater.schedule import schedule_from_dict
    from tidewater.statemachine import Command

    voters = ("n1", "n2", "n3")

    def build() -> Cluster:
        schedule = schedule_from_dict({
            "schema": 1, "name": "durable", "nodes": list(voters), "seed": 21, "ticks": 4000,
            "options": {"election_timeout": 50, "heartbeat_interval": 10, "pre_vote": True,
                         "sync_policy": "never"},
            "network": {"min_delay": 1, "max_delay": 3, "drop_rate": 0.0, "dup_rate": 0.0,
                         "dup_extra_delay": 4},
            "actions": [],
        })
        return Cluster(schedule, stop_on_violation=True)

    cluster = build()
    for _ in range(200):
        cluster.step()
        leader = cluster.leader()
        if leader is not None and cluster.now > 120:
            break
    leader = cluster.leader()
    assert leader is not None, "the cluster never elected a leader, so the scenario proves nothing"

    others = [node_id for node_id in voters if node_id != leader.node_id]
    cluster.network.partition([[leader.node_id, others[0]], [others[1]]])
    cluster.propose(Command("set", "durable", "yes"))
    follower = cluster.nodes[others[0]]
    for _ in range(300):
        if leader.commit_index >= 2 and follower.commit_index >= 2:
            break
        cluster.step()
    cluster.crash(follower.node_id)
    for _ in range(5):
        cluster.step()
    cluster.restart(follower.node_id)
    cluster.network.partition([[leader.node_id], [follower.node_id, others[1]]])

    try:
        for _ in range(1500):
            if cluster.violation is not None:
                break
            cluster.step()
    except SafetyViolation:
        pass

    assert cluster.violation is not None, (
        "a cluster that loses committed entries on a follower with a broken fsync is no longer "
        "reported: the safety checks have been optimised away"
    )
    assert cluster.violation.kind == "leader_completeness", (
        f"expected leader_completeness, got {cluster.violation.kind}"
    )


def test_the_repository_suite_still_passes():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

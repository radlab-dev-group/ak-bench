"""What the operators reported, stated as behaviour.

Five nodes, a log that is being compacted away, and one machine that was
reachable for none of it. Four complaints; none of them says how the missing
part is implemented.
"""

import subprocess
import sys
from pathlib import Path

from tidewater.cluster import Cluster
from tidewater.node import NodeOptions
from tidewater.schedule import Action, Schedule
from tidewater.network import NetworkOptions

FIVE = ("n1", "n2", "n3", "n4", "n5")
NEW_SCHEDULE = "compaction-catchup"


def repository() -> Path:
    for base in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (base / "tools" / "gen_schedules.py").is_file():
            return base
    raise AssertionError("the repository tools are not reachable from the workspace")


def shut_out(seed, ticks=2600):
    schedule = Schedule(
        name="public-catchup",
        nodes=FIVE,
        seed=seed,
        ticks=ticks,
        actions=[
            Action(at=1, kind="workload", args={"count": 20, "every": 15, "key_prefix": "a"}),
            Action(at=260, kind="isolate", args={"node": "n2"}),
            Action(at=280, kind="workload", args={"count": 70, "every": 15, "key_prefix": "b"}),
            Action(at=1700, kind="heal", args={}),
            Action(at=1740, kind="workload", args={"count": 30, "every": 15, "key_prefix": "c"}),
        ],
        node_options=NodeOptions(compaction_threshold=18, election_timeout=40, heartbeat_interval=8),
        network_options=NetworkOptions(min_delay=1, max_delay=4, drop_rate=0.03, dup_rate=0.02),
    )
    return Cluster(schedule)


def test_a_machine_shut_out_for_hours_still_comes_back():
    """The on-call complaint: a node that was cut off while the cluster kept
    writing was still empty of that afternoon's work a day after the link
    healed."""

    cluster = shut_out(5101)
    result = cluster.run()
    assert result.ok, result.render()

    n2 = cluster.nodes["n2"]
    assert n2.state_machine.get("b0") is not None, "it does not have the work from while it was away"
    assert n2.state_machine.get("c29") is not None, "and it is taking new work now"


def test_the_cluster_does_not_wait_for_the_machine_that_was_away():
    """Nobody else may stall while one node is being brought back up."""

    cluster = shut_out(5102)
    result = cluster.run()
    assert result.ok, result.render()
    assert min(result.commit_indexes.values()) > 0, f"somebody stopped committing: {result.commit_indexes}"
    assert min(result.applied.values()) > 0, f"somebody stopped applying: {result.applied}"


def test_everyone_ends_up_agreeing_including_the_machine_that_came_late():
    """The node that arrives last must end up with the same state as the nodes
    that never left, not a partial one."""

    cluster = shut_out(5103)
    result = cluster.run()
    assert result.ok, result.render()
    digests = {node.state_machine.digest() for node in cluster.nodes.values()}
    assert len(digests) == 1, "the cluster agrees on one state"
    assert cluster.nodes["n2"].commit_index > 0


def test_the_scenario_that_covers_this_is_in_the_corpus_and_reproduces():
    """The runbook is the procedure: the scenario is generated, the MANIFEST
    locks it, and the reference digest comes from the trace tool."""

    root = repository()
    assert (root / "schedules" / f"{NEW_SCHEDULE}.json").is_file(), "the corpus gained its catch-up schedule"
    assert (root / "traces" / f"{NEW_SCHEDULE}.digest").is_file(), "and its reference digest"

    generated = subprocess.run(
        [sys.executable, str(root / "tools" / "gen_schedules.py"), "--check"],
        cwd=str(root), capture_output=True, text=True, timeout=600,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr

    checked = subprocess.run(
        [sys.executable, str(root / "tools" / "reference_traces.py"), "--check", "--only", NEW_SCHEDULE],
        cwd=str(root), capture_output=True, text=True, timeout=600,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

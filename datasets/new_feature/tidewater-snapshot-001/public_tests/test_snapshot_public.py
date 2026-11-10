"""What the operators asked for, stated as behaviour.

The cluster runs out of log. Four complaints from the storage team, one of
which is the procedure the change has to arrive with; none of them says how
compaction is implemented.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tidewater.cluster import Cluster
from tidewater.membership import Configuration
from tidewater.node import LEADER, Node, NodeOptions
from tidewater.rng import SeedTree
from tidewater.schedule import schedule_from_dict
from tidewater.statemachine import Command
from tidewater.storage import Storage
from tidewater.clock import NodeClock
from tidewater.trace import Trace

ALONE = ("n1",)
FIVE = ("n1", "n2", "n3", "n4", "n5")
NEW_SCHEDULE = "compaction-quiet"


def repository() -> Path:
    for base in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (base / "tools" / "gen_schedules.py").is_file():
            return base
    raise AssertionError("the repository tools are not reachable from the workspace")


def node_alone(threshold, seed=7):
    tree = SeedTree(seed)
    node = Node(
        node_id="n1",
        config=Configuration.of(ALONE),
        storage=Storage("n1", ALONE),
        rng=tree.stream("n1", "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(compaction_threshold=threshold),
    )
    for _ in range(200):
        node.tick(node.global_tick + 1)
        if node.role == LEADER:
            break
    node.drain_outbox()
    return node


def write(node, count):
    for index in range(count):
        node.propose(Command("set", f"k{index}", str(index)))
        node.drain_outbox()
    return node


def test_a_node_that_writes_enough_stops_carrying_the_whole_log():
    """The disk team's complaint: a node that has applied a thousand entries
    should not have to keep all of them to know its state."""

    node = write(node_alone(threshold=6), 20)
    assert node.state_machine.get("k19") == "19", "the node still knows its state"
    assert node.log.base_index > 0, "the prefix it no longer needs is gone"
    assert len(node.log) < 20, "the log is shorter than the work it has applied"


def test_a_node_that_comes_back_after_a_crash_does_not_reread_history():
    """Restart is not a replay from the beginning of time: the node picks up
    from what it had already applied and takes on only the new work."""

    node = write(node_alone(threshold=6), 18)
    applied = node.state_machine.last_applied
    node.crash()
    node.restart()
    node.drain_outbox()

    assert node.state_machine.last_applied >= applied, "it remembers what it applied"
    assert node.state_machine.get("k17") == "17"
    assert node.commit_index >= applied

    for _ in range(200):
        node.tick(node.global_tick + 1)
        if node.role == LEADER:
            break
    node.propose(Command("set", "fresh", "yes"))
    node.drain_outbox()
    assert node.state_machine.get("fresh") == "yes"


def test_the_cluster_keeps_its_safety_promises_while_it_compacts():
    """A five-node cluster that writes and compacts at the same time must not
    break a single invariant, and must commit."""

    from tidewater.network import NetworkOptions
    from tidewater.schedule import Action, Schedule

    schedule = Schedule(
        name="public-quiet-compaction",
        nodes=FIVE,
        seed=33,
        ticks=900,
        actions=[Action(at=1, kind="workload", args={"count": 40, "every": 15, "key_prefix": "q"})],
        node_options=NodeOptions(compaction_threshold=16, election_timeout=40, heartbeat_interval=8),
        network_options=NetworkOptions(max_delay=3),
    )
    result = Cluster(schedule).run()
    assert result.ok, result.render()
    assert sum(result.commit_indexes.values()) > 0


def test_the_new_corpus_entry_arrives_through_the_tools_it_already_has():
    """The runbook is the procedure: the schedule is generated, the MANIFEST
    locks it, and the reference digest is recorded by the trace tool."""

    root = repository()
    assert (root / "schedules" / f"{NEW_SCHEDULE}.json").is_file(), "the corpus gained its compaction schedule"
    assert (root / "traces" / f"{NEW_SCHEDULE}.digest").is_file(), "and its reference digest"

    generated = subprocess.run(
        [sys.executable, str(root / "tools" / "gen_schedules.py"), "--check"],
        cwd=str(root), capture_output=True, text=True, timeout=300,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr

    checked = subprocess.run(
        [sys.executable, str(root / "tools" / "reference_traces.py"), "--check", "--only", NEW_SCHEDULE],
        cwd=str(root), capture_output=True, text=True, timeout=300,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

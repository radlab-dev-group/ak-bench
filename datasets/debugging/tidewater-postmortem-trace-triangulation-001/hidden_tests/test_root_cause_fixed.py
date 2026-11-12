"""The rule the defect breaks, stated as the code's own contract says it.

`NodeClock.set_skew` documents that changing a skew does not move the local
reading. The captured incident is what happens when it does: a node whose local
clock is rewound by 960 ticks cannot reach an election deadline for 960 ticks of
its own time, which is exactly "a majority that will not elect anybody".
"""

from __future__ import annotations

import pytest


def _root():
    """The checkout under test; hidden tests run one directory deeper when
    the dataset validator verifies a mutation."""
    from pathlib import Path

    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise AssertionError("the checkout under test was not found")


def _node(seed=7, voters=("n1", "n2", "n3", "n4", "n5")):
    from tidewater.clock import NodeClock
    from tidewater.membership import Configuration
    from tidewater.node import Node, NodeOptions
    from tidewater.rng import SeedTree
    from tidewater.storage import Storage
    from tidewater.trace import Trace

    node_id = voters[0]
    return Node(
        node_id=node_id,
        config=Configuration.of(voters),
        storage=Storage(node_id, voters),
        rng=SeedTree(seed).stream(node_id, "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(election_timeout=50, heartbeat_interval=10),
    )


def test_a_clock_keeps_the_time_it_has_counted_when_its_offset_changes():
    from tidewater.clock import NodeClock

    clock = NodeClock()
    for _ in range(500):
        clock.tick()
    before = clock.now
    clock.set_skew(offset=240)
    assert clock.now == before, (
        f"the clock was at {before} and set_skew(offset=240) moved it to {clock.now}; "
        "an offset declares where a clock stands, it does not move a reading"
    )


def test_the_clock_still_advances_at_the_new_rate_after_an_offset_change():
    from tidewater.clock import NodeClock

    clock = NodeClock()
    for _ in range(100):
        clock.tick()
    clock.set_skew(rate=3, offset=40)
    after = clock.now
    assert clock.tick() == after + 3, "a rate change stopped being honoured"


def test_the_offset_is_still_declared_even_though_it_no_longer_moves_the_clock():
    """The fix is a fix, not an omission.

    Ignoring offsets would satisfy "the clock is not rewound" and break the
    contract of ADR-0002 in the same breath: a skew action still has to record
    the offset it was given, and still say so.
    """
    from tidewater.clock import NodeClock

    clock = NodeClock()
    clock.set_skew(offset=240)
    assert clock.offset == 240, "set_skew stopped recording the offset it was given"
    assert "offset=240" in clock.describe(), (
        f"the skew is no longer described: {clock.describe()!r}"
    )


def test_a_rate_only_skew_leaves_a_declared_offset_alone():
    from tidewater.clock import NodeClock

    clock = NodeClock()
    clock.set_skew(offset=120)
    clock.set_skew(rate=2)
    assert (clock.offset, clock.rate) == (120, 2), "a rate change rewrote the offset"


def test_a_node_still_times_out_after_its_offset_is_changed():
    node = _node()
    for tick in range(200):
        node.tick(tick)
    local_before = node.clock.now
    node.set_skew(offset=40)
    deadline_in_the_future = node.election_deadline - node.clock.now
    assert node.clock.now >= local_before, "the node's clock was rewound by a skew action"
    assert 0 < deadline_in_the_future < 2 * node.options.election_timeout, (
        f"the node's election timer is {deadline_in_the_future} local ticks away; "
        "it must fire inside [T, 2T) so the cluster can elect somebody"
    )


def test_a_cluster_elects_promptly_after_a_node_is_skewed_by_offset():
    from tidewater.cluster import Cluster
    from tidewater.schedule import schedule_from_dict

    schedule = schedule_from_dict({
        "schema": 1, "name": "offset-skew", "nodes": ["n1", "n2", "n3", "n4", "n5"],
        "seed": 20261113, "ticks": 900,
        "options": {"election_timeout": 50, "heartbeat_interval": 10, "pre_vote": True},
        "network": {"min_delay": 1, "max_delay": 3, "drop_rate": 0.0, "dup_rate": 0.0,
                     "dup_extra_delay": 4},
        "actions": [
            {"at": 10, "kind": "workload", "count": 10, "every": 10, "key_prefix": "w"},
            {"at": 200, "kind": "skew", "node": "n3", "offset": 240},
            {"at": 260, "kind": "crash", "node": "n1"},
        ],
    })
    cluster = Cluster(schedule)
    for _ in range(260):
        cluster.step()
    assert cluster.leader() is not None, "no leader before the crash, so the scenario proves nothing"

    elected_at = None
    for _ in range(4 * cluster.schedule.node_options.election_timeout * 2):
        cluster.step()
        if cluster.leader() is not None and cluster.now > 280:
            elected_at = cluster.now
            break
    assert elected_at is not None, (
        "no leader within four election timeouts of the leader crashing, on the side of "
        "the cluster that still held a majority"
    )


def test_the_trace_of_the_twelve_schedules_is_untouched():
    import subprocess
    import sys as _sys
    from pathlib import Path

    root = _root()
    completed = subprocess.run(
        [_sys.executable, "tools/reference_traces.py", "--check"],
        cwd=root, capture_output=True, text=True, timeout=1800,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

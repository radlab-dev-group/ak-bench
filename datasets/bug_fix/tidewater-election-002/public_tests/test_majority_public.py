"""Complaints from a four-machine cluster.

Four machines were bought because the runbook said "one may be down at any
time". Two reports say the cluster did things with half its members, one
says it did the right thing when three of four were reachable, and one is
the check that the cluster still works when it is all there.

Nothing here says which rule is being broken; the reports are what the
operators saw on the wall.
"""

import pytest

from tidewater.clock import NodeClock
from tidewater.cluster import Cluster
from tidewater.membership import Configuration
from tidewater.messages import RequestVote, RequestVoteResponse
from tidewater.network import NetworkOptions
from tidewater.node import CANDIDATE, Node, NodeOptions
from tidewater.rng import SeedTree
from tidewater.schedule import Action, Schedule
from tidewater.storage import Storage
from tidewater.trace import Trace

QUAD = ("p", "q", "r", "s")
QUICK = {"election_timeout": 6, "heartbeat_interval": 1}


def machine(node_id, voters=QUAD, seed=1, **override):
    settings = dict(QUICK)
    settings.update(override)
    tree = SeedTree(seed)
    return Node(
        node_id=node_id,
        config=Configuration.of(voters),
        storage=Storage(node_id, tuple(voters)),
        rng=tree.stream(node_id, "election"),
        clock=NodeClock(),
        trace=Trace(),
        options=NodeOptions(**settings),
    )


def poll(node, role, limit=200):
    for _ in range(limit):
        if node.role == role:
            return node
        node.tick(node.global_tick + 1)
    raise AssertionError(f"{node.node_id} never became {role}: {node.describe()}")


def vote_out(voter_id, candidate, term, seed=20):
    voter = machine(voter_id, seed=seed)
    voter.receive(candidate.node_id, RequestVote(term=term, candidate_id=candidate.node_id,
                                                 last_log_index=0, last_log_term=0))
    for index, (destination, message) in enumerate(voter.outbox):
        if destination == candidate.node_id and isinstance(message, RequestVoteResponse):
            candidate.receive(voter_id, voter.outbox.pop(index)[1])
            return voter
    raise AssertionError(f"{voter_id} never answered {candidate.node_id}")


def split(groups, seed=5, ticks=500, actions=()):
    return Schedule(
        name=f"quad-{seed}",
        nodes=QUAD,
        seed=seed,
        ticks=ticks,
        actions=[Action(at=1, kind="partition", args={"groups": [list(g) for g in groups]})] + list(actions),
        node_options=NodeOptions(**QUICK),
        network_options=NetworkOptions(max_delay=2),
    )


def run(groups, seed=5, ticks=500, actions=()):
    cluster = Cluster(split(groups, seed=seed, ticks=ticks, actions=actions))
    result = cluster.run()
    assert result.ok, result.render()
    return cluster


def test_the_cluster_needs_three_of_its_four_machines_to_choose_somebody():
    """Two machines agreed on a candidate. There are four machines."""

    p = machine("p", seed=2, pre_vote=False)
    poll(p, CANDIDATE)
    q = vote_out("q", p, 1)
    assert p.role == CANDIDATE, "two of four machines is half the cluster, not most of it"

    r = vote_out("r", p, 1)
    assert p.role == "leader", "three of four is most of it"


def test_half_a_cluster_that_cannot_see_the_other_half_has_no_leader():
    """The wall showed a four-machine cluster split in two. Neither half may
    choose a leader, so the wall should have shown no leader at all."""

    cluster = run([["p", "q"], ["r", "s"]], seed=7)
    leaders = cluster.live_leaders()
    assert not leaders, f"both halves stayed quiet: {[n.describe() for n in leaders]}"


def test_half_a_cluster_that_cannot_see_the_other_half_commits_nothing():
    """Same split, with a client hammering both halves: nothing may be
    reported committed, because no half holds most of the four."""

    workload = Action(at=1, kind="workload", args={"count": 12, "every": 9})
    cluster = Cluster(Schedule(
        name="quad-split-workload",
        nodes=QUAD,
        seed=8,
        ticks=600,
        actions=[
            Action(at=1, kind="partition", args={"groups": [["p", "q"], ["r", "s"]]}),
            workload,
        ],
        node_options=NodeOptions(**QUICK),
        network_options=NetworkOptions(max_delay=2),
    ))
    result = cluster.run()
    assert result.ok, result.render()
    assert sum(result.commit_indexes.values()) == 0, (
        f"a minority half committed: {result.commit_indexes}"
    )


def test_three_reachable_machines_of_four_are_enough_for_everything():
    """The healthy report: three of four reachable, one leader, and the work
    commits."""

    workload = Action(at=1, kind="workload", args={"count": 10, "every": 12})
    cluster = Cluster(Schedule(
        name="quad-three-reachable",
        nodes=QUAD,
        seed=9,
        ticks=600,
        actions=[
            Action(at=1, kind="partition", args={"groups": [["p", "q", "r"], ["s"]]}),
            workload,
        ],
        node_options=NodeOptions(**QUICK),
        network_options=NetworkOptions(max_delay=2),
    ))
    result = cluster.run()
    assert result.ok, result.render()
    leaders = cluster.live_leaders()
    assert len(leaders) == 1, [n.describe() for n in leaders]
    assert leaders[0].node_id != "s", leaders[0].describe()
    assert sum(result.commit_indexes.values()) > 0, "the majority side made progress"

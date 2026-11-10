"""Whole-cluster scenarios driven through the schedule machinery."""

import pytest

from conftest import FIVE, THREE, act, make_schedule, run_until, wait_for_leader
from tidewater.cluster import Cluster, run_schedule
from tidewater.errors import NodeDownError
from tidewater.invariants import SafetyViolation
from tidewater.statemachine import Command


def all_applied_equal(cluster):
    digests = {n.state_machine.digest() for n in cluster.nodes.values() if n.alive}
    return len(digests) == 1


def test_cluster_elects_one_leader_commits_writes_and_converges():
    schedule = make_schedule(ticks=900, actions=[act(5, "workload", count=15, every=10, key_prefix="k")])
    cluster = Cluster(schedule)
    result = cluster.run()
    assert result.ok
    assert len(cluster.live_leaders()) == 1
    assert len(result.leaders_by_term) == 1
    assert set(result.commit_indexes.values()) == {16}  # no-op + 15 writes
    assert all_applied_equal(cluster)
    assert result.proposals["accepted"] == 15 and result.proposals["pending"] == 0
    assert len(cluster.trace) > 1000  # message-level events dominate


def test_same_seed_same_trace_different_seed_different_trace():
    schedule = make_schedule(ticks=600, actions=[act(5, "workload", count=5, every=10, key_prefix="k")])
    a = run_schedule(schedule)
    b = run_schedule(schedule)
    assert a.trace.to_jsonl() == b.trace.to_jsonl()
    assert a.digest == b.digest
    c = run_schedule(schedule, seed=99)
    assert c.trace.to_jsonl() != a.trace.to_jsonl()


def test_minority_side_cannot_commit_and_its_tail_is_truncated_after_heal():
    cluster = Cluster(make_schedule(ticks=2500))
    leader = wait_for_leader(cluster)
    run_until(cluster, lambda c: all(n.commit_index >= 1 for n in c.nodes.values()))
    others = [n for n in FIVE if n != leader.node_id]
    cluster.network.partition([[leader.node_id, others[0]], others[1:]])
    for i in range(3):
        cluster.propose(Command("set", f"minority{i}", "x"))
    minority_commit = leader.commit_index
    run_until(cluster, lambda c: leader.log.last_index >= minority_commit + 3, 100)
    for _ in range(400):
        cluster.step()
    assert leader.commit_index == minority_commit  # nothing new committed on the minority side
    majority_leader = next((n for n in cluster.nodes.values() if n.is_leader and n is not leader), None)
    assert majority_leader is not None and majority_leader.current_term > leader.current_term
    cluster.propose(Command("set", "majority", "y"))
    run_until(cluster, lambda c: majority_leader.commit_index > minority_commit, 200)
    cluster.network.heal()
    run_until(cluster, lambda c: all(n.log.last_index == majority_leader.log.last_index for n in c.nodes.values()), 400)
    assert leader.role != "leader"
    assert any(e.node == leader.node_id for e in cluster.trace.of_kind("truncate"))
    run_until(cluster, lambda c: all_applied_equal(c) and all(
        n.commit_index == majority_leader.commit_index for n in c.nodes.values()), 400)
    assert cluster.violation is None
    assert cluster.nodes[leader.node_id].state_machine.get("minority0") is None


def test_crashed_follower_restarts_from_durable_state_and_catches_up():
    cluster = Cluster(make_schedule(ticks=2000, actions=[act(5, "workload", count=10, every=10, key_prefix="k")]))
    leader = wait_for_leader(cluster)
    follower_id = next(n for n in FIVE if n != leader.node_id)
    run_until(cluster, lambda c: c.nodes[follower_id].commit_index >= 3)
    before = cluster.nodes[follower_id].log.last_index
    cluster.crash(follower_id)
    with pytest.raises(NodeDownError):
        cluster.crash(follower_id)
    for _ in range(200):
        cluster.step()
    assert cluster.nodes[follower_id].alive is False
    cluster.restart(follower_id)
    node = cluster.nodes[follower_id]
    assert node.log.last_index >= before  # durable log survived
    assert node.commit_index == 0 and node.state_machine.last_applied == 0  # volatile state rebuilt
    run_until(cluster, lambda c: node.commit_index == leader.commit_index and all_applied_equal(c), 400)
    assert node.restarts == 1
    assert cluster.violation is None


def _lose_committed_entries(sync_policy):
    """Three nodes. The leader commits with one follower while the other is
    cut off; that follower then crashes and restarts, and the leader is cut
    off. Whether a committed entry survives depends on the durability seam."""

    cluster = Cluster(make_schedule(nodes=THREE, ticks=4000, sync_policy=sync_policy), stop_on_violation=True)
    leader = wait_for_leader(cluster)
    f1, f2 = [cluster.nodes[n] for n in THREE if n != leader.node_id]
    cluster.network.partition([[leader.node_id, f1.node_id], [f2.node_id]])
    cluster.propose(Command("set", "durable", "yes"))
    run_until(cluster, lambda c: leader.commit_index >= 2 and f1.commit_index >= 2, 300)
    cluster.crash(f1.node_id)
    for _ in range(5):
        cluster.step()
    cluster.restart(f1.node_id)
    cluster.network.partition([[leader.node_id], [f1.node_id, f2.node_id]])
    for _ in range(1500):
        if cluster.violation is not None or any(n.is_leader and n is not leader for n in cluster.nodes.values()):
            break
        try:
            cluster.step()
        except SafetyViolation:
            break
    return cluster, leader, f1, f2


def test_durable_follower_keeps_committed_entries_across_restart():
    cluster, leader, f1, f2 = _lose_committed_entries("always")
    new_leader = next(n for n in cluster.nodes.values() if n.is_leader and n is not leader)
    assert new_leader is f1  # the only node whose log is complete can win
    assert cluster.violation is None
    assert new_leader.log.term_at(2) is not None


def test_losing_durable_state_on_crash_violates_leader_completeness():
    cluster, leader, f1, f2 = _lose_committed_entries("never")
    assert cluster.violation is not None
    assert cluster.violation.kind == "leader_completeness"
    assert f1.storage.lost_writes >= 1
    assert cluster.trace.last("violation").fields["violation"] == "leader_completeness"
    result = cluster.result()
    assert not result.ok and result.to_dict()["violation"]["kind"] == "leader_completeness"


def test_fast_clock_node_does_not_steal_leadership_thanks_to_prevote():
    schedule = make_schedule(ticks=1500, actions=[
        act(5, "workload", count=10, every=10, key_prefix="k"),
        act(200, "skew", node="n3", rate=4),
        act(400, "workload", count=10, every=10, key_prefix="m"),
    ])
    cluster = Cluster(schedule)
    result = cluster.run()
    assert result.ok
    assert len(result.leaders_by_term) == 1
    n3 = cluster.nodes["n3"]
    assert n3.timeouts > 3 or n3.is_leader  # it kept timing out early...
    assert all(not e.fields["granted"] for e in cluster.trace.of_kind("prevote") if e.fields["candidate"] == "n3") \
        or n3.is_leader
    assert set(result.commit_indexes.values()) == {21}


def test_run_schedule_tick_override_and_give_up():
    schedule = make_schedule(ticks=3000, give_up_after=30, actions=[
        act(2, "propose", command={"op": "set", "key": "early", "value": "1"}),
        act(2000, "workload", count=3, every=10, key_prefix="late"),
    ])
    result = run_schedule(schedule, ticks=300)
    assert result.ticks == 300
    assert result.trace.last("end").fields["ticks"] == 300
    assert result.proposals["given_up"] == 1  # no leader within 30 ticks of tick 2
    assert result.proposals["offered"] == 1  # the late workload was never reached


def test_cluster_describe_and_node_describe_are_readable(cluster):
    wait_for_leader(cluster)
    text = cluster.describe()
    assert "leader" in text and "network sent=" in text
    assert cluster.leader().describe().split()[1] == "leader"

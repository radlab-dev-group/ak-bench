"""The declared-but-unimplemented surfaces raise, and the rest runs without them."""

import pytest

from conftest import make_node, make_schedule, make_single_leader
from tidewater import membership, snapshot
from tidewater.cluster import Cluster
from tidewater.errors import FeatureNotImplemented
from tidewater.messages import InstallSnapshot
from tidewater.statemachine import Command
from tidewater.storage import SnapshotRecord


def test_snapshot_entry_points_raise_feature_not_implemented():
    node = make_node("n1", voters=("n1",))
    policy = snapshot.SnapshotPolicy(threshold=4)
    assert policy.enabled and not snapshot.SnapshotPolicy().enabled
    for call in (
        lambda: snapshot.take_snapshot(node, policy),
        lambda: snapshot.send_snapshot_chunk(node, "n2", 0),
        lambda: snapshot.on_snapshot_ack(node, "n2", None),
        lambda: snapshot.resume_after_restart(node),
    ):
        with pytest.raises(NotImplementedError):
            call()
    with pytest.raises(FeatureNotImplemented):
        snapshot.take_snapshot(node, policy)
    with pytest.raises(ValueError):
        snapshot.SnapshotPolicy(chunk_size=0)


def test_follower_receiving_install_snapshot_hits_the_stub():
    node = make_node("n2")
    msg = InstallSnapshot(term=1, leader_id="n1", last_included_index=3, last_included_term=1,
                          offset=0, data=b"x", done=True)
    with pytest.raises(FeatureNotImplemented):
        node.receive("n1", msg)
    assert node.current_term == 1  # the term was adopted before the stub was reached


def test_compaction_threshold_triggers_the_stub_once_enough_is_applied():
    node = make_single_leader("n1", compaction_threshold=3)
    assert node.log.last_index == 1  # the no-op
    node.propose(Command("set", "a", "1"))
    with pytest.raises(FeatureNotImplemented):
        node.propose(Command("set", "b", "2"))  # third entry (no-op + 2) reaches the threshold
    schedule = make_schedule(ticks=100, compaction_threshold=0)
    assert Cluster(schedule).run().ok  # zero disables: the default path never calls in


def test_membership_change_stubs_raise_and_configuration_is_real():
    config = membership.Configuration.of(["n1", "n2", "n3"])
    assert config.majority_size == 2
    assert config.has_majority(["n1", "n2", "zz"]) and not config.has_majority(["n1", "zz"])
    assert config.peers_of("n2") == ("n1", "n3")
    joint = membership.JointConfiguration(config, membership.Configuration.of(["n3", "n4", "n5"]))
    assert joint.all_voters == frozenset("n1 n2 n3 n4 n5".split())
    with pytest.raises(FeatureNotImplemented):
        joint.has_majority(["n1", "n2", "n3", "n4"])
    change = membership.MembershipChange(old=config)
    for call in (
        lambda: change.begin(["n4"]),
        lambda: change.propose_joint(),
        lambda: change.on_joint_committed(),
        lambda: change.on_final_committed("n1"),
        lambda: change.learner_caught_up("n4", 1, 2),
        lambda: membership.configuration_from_entry_payload({"config": "joint"}),
    ):
        with pytest.raises(NotImplementedError):
            call()


def test_snapshot_record_is_storable_even_though_nothing_writes_it():
    from tidewater.storage import PersistentState, Storage
    storage = Storage("n1", ("n1",))
    record = SnapshotRecord(last_included_index=5, last_included_term=2, state=b"{}", config=("n1",))
    storage.save_snapshot(record)
    assert storage.snapshot is record
    again = PersistentState.from_dict(storage.durable_view().to_dict())
    assert again.snapshot.last_included_term == 2 and again.snapshot.state == b"{}"

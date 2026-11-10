"""The declared-but-unimplemented surfaces raise, and the rest runs without them."""

import pytest

from conftest import make_node, make_schedule, make_single_leader
from tidewater import membership, snapshot
from tidewater.cluster import Cluster
from tidewater.errors import FeatureNotImplemented, StorageError
from tidewater.messages import InstallSnapshot
from tidewater.statemachine import Command
from tidewater.storage import SnapshotRecord


def test_the_snapshot_surface_is_implemented():
    node = make_node("n1", voters=("n1",))
    policy = snapshot.SnapshotPolicy(threshold=4)
    assert policy.enabled and not snapshot.SnapshotPolicy().enabled
    with pytest.raises(ValueError):
        snapshot.SnapshotPolicy(chunk_size=0)
    # take, resume and the transfer are all real now (SPEC 6.2 - 6.6); with no
    # snapshot on disk there is nothing to send, which is a storage error.
    with pytest.raises(StorageError):
        snapshot.send_snapshot_chunk(node, "n2", 0)


def test_a_snapshot_install_replaces_the_state_and_the_log():
    leader = make_single_leader("n1", compaction_threshold=4)
    for i in range(10):
        leader.propose(Command("set", f"k{i}", str(i)))
    record = leader.storage.snapshot
    assert record is not None

    follower = make_node("n2", voters=("n1", "n2", "n3"))
    msg = InstallSnapshot(term=1, leader_id="n1",
                          last_included_index=record.last_included_index,
                          last_included_term=record.last_included_term,
                          offset=0, data=record.state, done=True)
    follower.receive("n1", msg)
    (dst, reply), = follower.drain_outbox()
    assert dst == "n1" and reply.done and reply.offset == len(record.state)
    assert follower.state_machine.get("k9") == "9"
    assert follower.log.base_index == record.last_included_index
    assert follower.commit_index == record.last_included_index


def test_compaction_snapshots_the_state_machine_and_keeps_the_boundary():
    node = make_single_leader("n1", compaction_threshold=4)
    for i in range(6):
        node.propose(Command("set", f"k{i}", str(i)))
    assert node.storage.snapshot is not None
    record = node.storage.snapshot
    assert record.last_included_index == node.state_machine.last_applied
    assert node.log.base_index <= record.last_included_index
    assert node.log.base_term == node.log.term_at(node.log.base_index)
    # The state machine survived the compaction.
    assert node.state_machine.get("k5") == "5"
    # And a crash before the next apply loses nothing committed.
    node.crash()
    node.restart()
    assert node.storage.snapshot is not None
    assert node.state_machine.get("k5") == "5"
    assert node.commit_index >= record.last_included_index


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

"""Log replication and the commit rules, one node at a time."""

from conftest import make_node, tick_until_outbox
from tidewater.log import ENTRY_NOOP, Entry
from tidewater.messages import AppendEntries, AppendEntriesResponse, RequestVoteResponse
from tidewater.node import LEADER
from tidewater.statemachine import Command


def entries(*terms, start=1):
    return tuple(Entry(index=start + i, term=t, kind=ENTRY_NOOP) for i, t in enumerate(terms))


def make_leader(voters=("n1", "n2", "n3", "n4", "n5")):
    node = make_node("n1", voters=voters, pre_vote=False)
    tick_until_outbox(node)
    node.drain_outbox()
    for voter in list(voters)[1:]:
        if node.role != LEADER:
            node.receive(voter, RequestVoteResponse(term=1, voter_id=voter, granted=True))
    assert node.role == LEADER
    node.drain_outbox()
    return node


def test_follower_rejects_mismatched_prefix_with_a_conflict_hint():
    node = make_node("n2")
    node.receive("n1", AppendEntries(term=1, leader_id="n1", prev_log_index=0, prev_log_term=0, entries=entries(1, 1)))
    node.drain_outbox()
    node.receive("n1", AppendEntries(term=1, leader_id="n1", prev_log_index=5, prev_log_term=1, entries=entries(1, start=6)))
    (_, reply), = node.drain_outbox()
    assert isinstance(reply, AppendEntriesResponse) and not reply.success
    assert (reply.conflict_index, reply.conflict_term) == (3, 0)
    assert node.log.last_index == 2
    assert node.trace.last("reject_append").fields["reason"] == "log_mismatch"


def test_follower_keeps_entries_on_stale_duplicate_and_truncates_only_on_conflict():
    node = make_node("n2")
    node.receive("n1", AppendEntries(term=2, leader_id="n1", prev_log_index=0, prev_log_term=0, entries=entries(1, 1, 2, 2)))
    node.drain_outbox()
    # A delayed duplicate of an earlier append: nothing may be truncated.
    node.receive("n1", AppendEntries(term=2, leader_id="n1", prev_log_index=0, prev_log_term=0, entries=entries(1, 1)))
    (_, reply), = node.drain_outbox()
    assert reply.success and reply.match_index == 2
    assert node.log.terms() == [1, 1, 2, 2]
    assert node.trace.of_kind("truncate") == []
    # A genuine conflict at index 3 from a term-3 leader.
    node.receive("n1", AppendEntries(term=3, leader_id="n1", prev_log_index=2, prev_log_term=1, entries=entries(3, start=3)))
    (_, reply), = node.drain_outbox()
    assert reply.success and reply.match_index == 3
    assert node.log.terms() == [1, 1, 3]
    assert node.trace.last("truncate").fields["removed"] == 2


def test_follower_commit_is_min_of_leader_commit_and_last_new_entry():
    node = make_node("n2")
    node.receive("n1", AppendEntries(term=1, leader_id="n1", prev_log_index=0, prev_log_term=0,
                                     entries=entries(1, 1), leader_commit=10))
    assert node.commit_index == 2
    assert node.state_machine.last_applied == 2
    node.drain_outbox()
    node.receive("n1", AppendEntries(term=1, leader_id="n1", prev_log_index=2, prev_log_term=1,
                                     entries=(), leader_commit=1))
    assert node.commit_index == 2  # never goes backwards


def test_leader_commits_only_entries_of_its_own_term():
    leader = make_leader()
    # Pretend an older-term entry sits below the no-op: rebuild the log.
    leader.log.truncate_from(1)
    leader.storage.set_term(1, "n1")
    leader.log.append(Entry(1, 1, ENTRY_NOOP))
    leader.storage.set_term(3, "n1")
    leader.log.append(Entry(2, 3, ENTRY_NOOP))
    leader.storage.save_log(leader.log)
    leader.match_index = {"n1": 2}
    for peer in ("n2", "n3"):
        leader.receive(peer, AppendEntriesResponse(term=3, follower_id=peer, success=True, match_index=1))
    assert leader.commit_index == 0  # index 1 is term 1: a majority is not enough
    for peer in ("n2", "n3"):
        leader.receive(peer, AppendEntriesResponse(term=3, follower_id=peer, success=True, match_index=2))
    assert leader.commit_index == 2  # the term-3 entry commits, and index 1 with it
    assert [e.fields["index"] for e in leader.trace.of_kind("commit")] == [2]
    assert leader.state_machine.last_applied == 2


def test_leader_counts_a_majority_of_the_configuration_not_of_responders():
    leader = make_leader()
    leader.propose(Command("set", "k", "v"))
    leader.drain_outbox()
    assert leader.log.last_index == 2
    leader.receive("n2", AppendEntriesResponse(term=1, follower_id="n2", success=True, match_index=2))
    assert leader.commit_index == 0  # self + n2 = 2 of 5
    leader.receive("n9", AppendEntriesResponse(term=1, follower_id="n9", success=True, match_index=2))
    assert leader.commit_index == 0  # a stranger's ack does not count
    leader.receive("n3", AppendEntriesResponse(term=1, follower_id="n3", success=True, match_index=2))
    assert leader.commit_index == 2  # self + n2 + n3 = 3 of 5


def test_leader_backs_up_next_index_from_the_conflict_hint():
    leader = make_leader()
    for _ in range(4):
        leader.propose(Command("set", "k", "v"))
    leader.drain_outbox()
    assert leader.next_index["n2"] == 1  # next_index only moves on acknowledgements
    leader.receive("n2", AppendEntriesResponse(term=1, follower_id="n2", success=True, match_index=5))
    leader.drain_outbox()
    assert leader.next_index["n2"] == 6
    # The follower lost its log (say, a crash with a broken disk) and now rejects everything.
    leader.receive("n2", AppendEntriesResponse(term=1, follower_id="n2", success=False,
                                               conflict_index=1, conflict_term=0))
    assert leader.next_index["n2"] == 1
    (dst, msg), = [(d, m) for d, m in leader.drain_outbox() if isinstance(m, AppendEntries)]
    assert dst == "n2" and msg.prev_log_index == 0 and len(msg.entries) == 5


def test_stale_append_response_from_an_old_term_is_ignored():
    leader = make_leader()
    leader.propose(Command("set", "k", "v"))
    leader.drain_outbox()
    leader.receive("n2", AppendEntriesResponse(term=0, follower_id="n2", success=True, match_index=2))
    leader.receive("n3", AppendEntriesResponse(term=0, follower_id="n3", success=True, match_index=2))
    assert leader.commit_index == 0
    assert leader.role == LEADER

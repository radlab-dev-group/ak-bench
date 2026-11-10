"""Elections at the level of one node fed messages by hand."""

import pytest

from conftest import make_node, make_single_leader, tick_until_outbox
from tidewater.log import ENTRY_NOOP, Entry
from tidewater.messages import AppendEntries, RequestVote, RequestVoteResponse
from tidewater.node import CANDIDATE, FOLLOWER, LEADER, PRE_CANDIDATE


def test_timeout_fires_within_the_randomised_window_and_starts_a_prevote():
    node = make_node("n1", election_timeout=50)
    ticks = tick_until_outbox(node)
    assert 50 <= ticks < 100
    assert node.role == PRE_CANDIDATE
    assert node.current_term == 0  # pre-vote changes nothing persistent
    assert node.storage.write_count == 0
    requests = [m for _, m in node.outbox]
    assert all(isinstance(m, RequestVote) and m.pre_vote and m.term == 1 for m in requests)
    assert sorted(dst for dst, _ in node.outbox) == ["n2", "n3"]


def test_prevote_majority_starts_a_real_election_with_persisted_term_and_vote():
    node = make_node("n1")
    tick_until_outbox(node)
    node.drain_outbox()
    node.receive("n2", RequestVoteResponse(term=0, voter_id="n2", granted=True, pre_vote=True))
    assert node.role == CANDIDATE
    assert node.current_term == 1 and node.voted_for == "n1"
    assert node.storage.sync_count >= 1
    assert all(isinstance(m, RequestVote) and not m.pre_vote and m.term == 1 for _, m in node.outbox)


def test_vote_is_granted_once_per_term_and_persisted_before_the_reply():
    node = make_node("n3")
    node.receive("n1", RequestVote(term=1, candidate_id="n1", last_log_index=0, last_log_term=0))
    (dst, reply), = node.drain_outbox()
    assert dst == "n1" and reply.granted and reply.term == 1
    assert node.storage.durable_view().voted_for == "n1"
    node.receive("n2", RequestVote(term=1, candidate_id="n2", last_log_index=0, last_log_term=0))
    (_, reply), = node.drain_outbox()
    assert not reply.granted
    assert node.trace.last("vote").fields["reason"] == "already_voted"


def test_vote_denied_when_candidate_log_is_behind():
    node = make_node("n3")
    node.log.append(Entry(1, 1, ENTRY_NOOP))
    node.log.append(Entry(2, 2, ENTRY_NOOP))
    node.storage.set_term(2, None)
    node.receive("n1", RequestVote(term=3, candidate_id="n1", last_log_index=5, last_log_term=1))
    (_, reply), = node.drain_outbox()
    assert not reply.granted and reply.term == 3
    assert node.current_term == 3 and node.voted_for is None  # term adopted, vote withheld
    node.receive("n2", RequestVote(term=3, candidate_id="n2", last_log_index=2, last_log_term=2))
    (_, reply), = node.drain_outbox()
    assert reply.granted


def test_leader_steps_down_on_a_higher_term_and_candidate_yields_to_a_leader():
    leader = make_single_leader("n1")  # a one-node cluster elects itself
    assert leader.role == LEADER and leader.commit_index == 1
    leader.receive("n2", RequestVoteResponse(term=5, voter_id="n2", granted=False))
    assert leader.role == FOLLOWER and leader.current_term == 5
    assert leader.trace.last("step_down").fields["was"] == "leader"

    candidate = make_node("n2", pre_vote=False)
    tick_until_outbox(candidate)
    assert candidate.role == CANDIDATE and candidate.current_term == 1
    candidate.receive("n1", AppendEntries(term=1, leader_id="n1", prev_log_index=0, prev_log_term=0))
    assert candidate.role == FOLLOWER and candidate.leader_id == "n1"


def test_prevote_is_denied_while_the_leader_lease_is_fresh():
    node = make_node("n3", election_timeout=50)
    node.tick(1)
    node.receive("n1", AppendEntries(term=1, leader_id="n1", prev_log_index=0, prev_log_term=0))
    node.drain_outbox()
    node.receive("n2", RequestVote(term=2, candidate_id="n2", last_log_index=0, last_log_term=0, pre_vote=True))
    (_, reply), = node.drain_outbox()
    assert not reply.granted and reply.pre_vote
    assert node.trace.last("prevote").fields["reason"] == "leader_lease"
    # Let T local ticks pass without a heartbeat: the lease lapses.
    for t in range(2, 2 + 50):
        node.clock.tick()
    node.receive("n2", RequestVote(term=2, candidate_id="n2", last_log_index=0, last_log_term=0, pre_vote=True))
    (_, reply), = node.drain_outbox()
    assert reply.granted
    assert node.current_term == 1  # granting a pre-vote never touches the term


def test_leaders_deny_prevotes_and_prevote_denial_with_higher_term_steps_down():
    leader = make_single_leader("n1")
    leader.receive("n9", RequestVote(term=2, candidate_id="n9", last_log_index=0, last_log_term=0, pre_vote=True))
    (_, reply), = leader.drain_outbox()
    assert not reply.granted and leader.trace.last("prevote").fields["reason"] == "is_leader"

    node = make_node("n2")
    tick_until_outbox(node)
    node.drain_outbox()
    node.receive("n3", RequestVoteResponse(term=7, voter_id="n3", granted=False, pre_vote=True))
    assert node.role == FOLLOWER and node.current_term == 7


def test_without_prevote_a_timeout_goes_straight_to_an_election():
    node = make_node("n1", pre_vote=False)
    tick_until_outbox(node)
    assert node.role == CANDIDATE and node.current_term == 1
    assert node.trace.of_kind("prevote_start") == []


def test_winning_an_election_appends_a_noop_and_heartbeats_every_peer():
    node = make_node("n1", voters=("n1", "n2", "n3", "n4", "n5"), pre_vote=False)
    tick_until_outbox(node)
    node.drain_outbox()
    node.receive("n2", RequestVoteResponse(term=1, voter_id="n2", granted=True))
    assert node.role == CANDIDATE  # 2 of 5 is not a majority
    node.receive("n4", RequestVoteResponse(term=1, voter_id="n4", granted=True))
    assert node.role == LEADER
    assert node.log.last_index == 1 and node.log.at(1).kind == ENTRY_NOOP
    appends = [(dst, m) for dst, m in node.drain_outbox() if isinstance(m, AppendEntries)]
    assert sorted(dst for dst, _ in appends) == ["n2", "n3", "n4", "n5"]
    assert all(m.prev_log_index == 0 and len(m.entries) == 1 for _, m in appends)
    assert node.commit_index == 0  # not until a majority acknowledges

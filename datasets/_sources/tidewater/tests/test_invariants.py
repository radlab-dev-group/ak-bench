"""The six safety invariants, exercised on hand-built node stand-ins."""

from types import SimpleNamespace

import pytest

from tidewater.invariants import VIOLATION_KINDS, InvariantMonitor, SafetyViolation
from tidewater.log import ENTRY_NOOP, Entry, RaftLog
from tidewater.membership import Configuration, disjoint_quorums_possible
from tidewater.statemachine import KVStateMachine


def fake(node_id, terms, term=1, leader=False, commit=0, applied=0, restarts=0, voters=("a", "b", "c")):
    log = RaftLog([Entry(i + 1, t, ENTRY_NOOP) for i, t in enumerate(terms)])
    sm = KVStateMachine()
    for i in range(applied):
        sm.apply(i + 1, None)
    return SimpleNamespace(
        node_id=node_id, alive=True, is_leader=leader, current_term=term, commit_index=commit,
        restarts=restarts, log=log, state_machine=sm, config=Configuration.of(voters),
    )


def test_violation_kinds_are_closed():
    assert VIOLATION_KINDS == ("election_safety", "log_matching", "leader_completeness",
                               "state_machine_safety", "commit_regression", "membership_split")
    with pytest.raises(ValueError):
        SafetyViolation("split_brain", "nope")
    v = SafetyViolation("election_safety", "two leaders", tick=7)
    assert str(v) == "election_safety at tick 7: two leaders"


def test_election_safety_two_leaders_same_term():
    monitor = InvariantMonitor()
    monitor.check([fake("a", [1], leader=True, term=1), fake("b", [1], term=1)], 1)
    with pytest.raises(SafetyViolation) as info:
        monitor.check([fake("a", [1], leader=True, term=1), fake("b", [1], leader=True, term=1)], 2)
    assert info.value.kind == "election_safety"
    # A new leader in a new term is fine.
    monitor.check([fake("a", [1], term=2), fake("b", [1, 2], leader=True, term=2)], 3)
    assert monitor.leaders_by_term == {1: "a", 2: "b"}


def test_log_matching_same_term_at_index_but_different_prefix():
    monitor = InvariantMonitor()
    monitor.check([fake("a", [1, 1, 2]), fake("b", [1, 1, 2]), fake("c", [1, 3])], 1)  # c diverges: allowed
    with pytest.raises(SafetyViolation) as info:
        monitor.check([fake("a", [1, 2, 3]), fake("b", [1, 1, 3])], 2)
    assert info.value.kind == "log_matching"
    assert "index 3" in info.value.detail and "index 2" in info.value.detail


def test_leader_completeness_new_leader_lacks_committed_entry():
    monitor = InvariantMonitor()
    monitor.check([fake("a", [1, 1], leader=True, term=1, commit=2), fake("b", [1, 1], commit=2), fake("c", [])], 1)
    assert sorted(monitor.committed) == [1, 2]
    with pytest.raises(SafetyViolation) as info:
        monitor.check([fake("c", [2], leader=True, term=2)], 2)
    assert info.value.kind == "leader_completeness"
    monitor2 = InvariantMonitor()
    monitor2.check([fake("a", [1, 1], leader=True, term=1, commit=2)], 1)
    with pytest.raises(SafetyViolation) as info:
        monitor2.check([fake("c", [1, 2, 2], leader=True, term=2)], 2)
    assert info.value.kind == "leader_completeness" and "holds term 2 at index 2" in info.value.detail


def test_state_machine_safety_conflicting_applied_or_committed_entries():
    monitor = InvariantMonitor()
    monitor.check([fake("a", [1, 1], commit=2, applied=2)], 1)
    with pytest.raises(SafetyViolation) as info:
        monitor.check([fake("b", [1, 2], commit=2, applied=2)], 2)
    assert info.value.kind == "state_machine_safety"
    monitor2 = InvariantMonitor()
    monitor2.check([fake("a", [1, 1], commit=2)], 1)
    with pytest.raises(SafetyViolation) as info:
        monitor2.check([fake("b", [1, 3], commit=2)], 2)
    assert info.value.kind == "state_machine_safety" and "committed" in info.value.detail


def test_commit_regression_unless_restarted():
    monitor = InvariantMonitor()
    monitor.check([fake("a", [1, 1, 1], commit=3)], 1)
    with pytest.raises(SafetyViolation) as info:
        monitor.check([fake("a", [1, 1, 1], commit=2)], 2)
    assert info.value.kind == "commit_regression"
    fresh = InvariantMonitor()
    fresh.check([fake("a", [1, 1, 1], commit=3)], 1)
    fresh.check([fake("a", [1, 1, 1], commit=0, restarts=1)], 2)  # a restart resets the baseline
    fresh.check([fake("a", [1, 1, 1], commit=3, restarts=1)], 3)


def test_membership_split_two_configurations_with_disjoint_majorities():
    a = Configuration.of(["n1", "n2", "n3"])
    b = Configuration.of(["n3", "n4", "n5"])
    c = Configuration.of(["n1", "n2", "n3", "n4"])
    five = Configuration.of(["n1", "n2", "n3", "n4", "n5"])
    assert disjoint_quorums_possible(a, b)        # {n1,n2} and {n4,n5}
    assert not disjoint_quorums_possible(a, c)    # every 3-of-4 meets every 2-of-3
    assert disjoint_quorums_possible(a, five)     # {n1,n2} and {n3,n4,n5}: why 3 -> 5 needs joint consensus
    assert not disjoint_quorums_possible(a, a)
    monitor = InvariantMonitor()
    monitor.check([fake("n1", [], voters=a.voters), fake("n5", [], voters=c.voters)], 1)
    with pytest.raises(SafetyViolation) as info:
        monitor.check([fake("n1", [], voters=a.voters), fake("n5", [], voters=b.voters)], 2)
    assert info.value.kind == "membership_split"


def test_monitor_summary_and_selective_enable():
    monitor = InvariantMonitor(enabled=("log_matching",))
    monitor.check([fake("a", [1], leader=True), fake("b", [1], leader=True)], 1)  # election safety off
    assert monitor.summary()["checks"] == 1
    full = InvariantMonitor()
    full.check([fake("a", [1, 1], leader=True, commit=2)], 1)
    assert full.summary()["highest_committed"] == 2 and full.summary()["leaders_by_term"] == {1: "a"}

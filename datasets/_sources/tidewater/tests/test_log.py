"""The log: matching, truncation on conflict, the up-to-date rule."""

import pytest

from tidewater.errors import StorageError
from tidewater.log import ENTRY_NOOP, Entry, RaftLog, entry_from_dict
from tidewater.statemachine import Command


def entries(*terms, start=1):
    return [Entry(index=start + i, term=t, kind=ENTRY_NOOP) for i, t in enumerate(terms)]


def test_log_is_dense_and_terms_never_decrease():
    log = RaftLog(entries(1, 1, 2))
    assert log.last_index == 3 and log.last_term == 2
    with pytest.raises(StorageError):
        RaftLog([Entry(index=2, term=1, kind=ENTRY_NOOP)])
    with pytest.raises(StorageError):
        RaftLog(entries(2, 1))


def test_matching_rule_treats_index_zero_as_empty_prefix():
    log = RaftLog(entries(1, 1, 3))
    assert log.matches(0, 0)
    assert log.matches(2, 1)
    assert log.matches(3, 3)
    assert not log.matches(3, 2)
    assert not log.matches(4, 3)  # nothing there


def test_up_to_date_compares_term_then_index():
    log = RaftLog(entries(1, 2, 2))
    assert log.is_up_to_date(3, 2)
    assert log.is_up_to_date(5, 2)
    assert log.is_up_to_date(1, 3)  # higher last term wins despite shorter log
    assert not log.is_up_to_date(2, 2)
    assert not log.is_up_to_date(9, 1)


def test_append_from_leader_keeps_matching_entries_and_truncates_only_on_conflict():
    log = RaftLog(entries(1, 1, 2, 2))
    # Same prefix, a stale duplicate: nothing is truncated or appended.
    ok, truncated, appended, match = log.append_from_leader(1, 1, entries(1, start=2))
    assert (ok, truncated, appended, match) == (True, 0, 0, 2)
    assert log.last_index == 4
    # Conflict at index 3 (term 2 on disk, term 3 from the leader): cut from 3.
    ok, truncated, appended, match = log.append_from_leader(2, 1, entries(3, 3, start=3))
    assert (ok, truncated, appended, match) == (True, 2, 2, 4)
    assert log.terms() == [1, 1, 3, 3]


def test_append_from_leader_rejects_mismatched_prefix_without_change():
    log = RaftLog(entries(1, 1))
    ok, *_ = log.append_from_leader(2, 2, entries(2, start=3))
    assert not ok
    assert log.terms() == [1, 1]
    assert log.conflict_hint(2) == (1, 1)      # term 1 starts at index 1
    assert log.conflict_hint(7) == (3, 0)      # nothing there: last_index + 1


def test_truncate_refuses_compacted_prefix_and_compact_keeps_boundary_term():
    log = RaftLog(entries(1, 1, 2, 2, 3))
    assert log.compact_to(3, 2) == 3
    assert (log.base_index, log.base_term, log.first_index) == (3, 2, 4)
    assert log.term_at(3) == 2
    assert log.matches(3, 2)
    with pytest.raises(StorageError):
        log.truncate_from(3)
    with pytest.raises(StorageError):
        log.compact_to(5, 9)


def test_entry_round_trips_through_dict():
    entry = Entry(index=4, term=2, command=Command(op="set", key="a", value="1", client="c", seq=3))
    again = entry_from_dict(entry.to_dict())
    assert again == entry
    assert again.summary() == "4/2:set a=1"
    with pytest.raises(ValueError):
        Entry(index=0, term=1)
    with pytest.raises(ValueError):
        Entry(index=1, term=1, kind="mystery")

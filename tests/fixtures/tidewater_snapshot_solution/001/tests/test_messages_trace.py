"""Wire messages and the trace format."""

import pytest

from tidewater.errors import TraceError
from tidewater.log import ENTRY_NOOP, Entry
from tidewater.messages import (
    MESSAGE_KINDS,
    AppendEntries,
    InstallSnapshot,
    RequestVote,
    message_from_dict,
)
from tidewater.trace import DIGEST_KINDS, Trace, first_divergence


def test_messages_round_trip_through_dict():
    msg = AppendEntries(term=3, leader_id="n1", prev_log_index=4, prev_log_term=2,
                        entries=(Entry(5, 3, ENTRY_NOOP),), leader_commit=4)
    assert message_from_dict(msg.to_dict()) == msg
    snap = InstallSnapshot(term=1, leader_id="n1", last_included_index=9, last_included_term=1,
                           offset=0, data=b"\x00\x01", done=True)
    assert message_from_dict(snap.to_dict()) == snap
    assert RequestVote(1, "n1", 0, 0, pre_vote=True).summary().startswith("RequestVote[prevote]")
    assert "RequestVote" in MESSAGE_KINDS and len(MESSAGE_KINDS) == 7
    with pytest.raises(ValueError):
        message_from_dict({"kind": "Gossip", "term": 1})


def test_trace_is_append_only_and_digest_covers_only_committed_visible_kinds():
    trace = Trace()
    trace.record(1, "n1", "send", seq=1)
    trace.record(2, "n1", "commit", index=1, term=1)
    trace.record(2, "n1", "apply", index=1, term=1)
    assert len(trace) == 3
    assert [e.kind for e in trace.digest_events()] == ["commit", "apply"]
    assert set(DIGEST_KINDS) == {"commit", "apply", "snapshot", "violation"}
    only = Trace()
    only.record(2, "n1", "commit", index=1, term=1)
    only.record(2, "n1", "apply", index=1, term=1)
    assert only.digest() == trace.digest()  # message events do not take part


def test_trace_jsonl_round_trip_and_text_render(tmp_path):
    trace = Trace()
    trace.record(0, "", "schedule", name="x")
    trace.record(5, "n2", "leader", term=1, noop_index=1)
    path = tmp_path / "t.jsonl"
    assert trace.write_jsonl(path) == 2
    again = Trace.read_jsonl(path)
    assert again.to_jsonl() == trace.to_jsonl()
    assert again.digest() == trace.digest()
    text = trace.render_text()
    assert "t=000005 n2     leader" in text
    assert text.splitlines()[0].startswith("0000000 t=000000 -")


def test_trace_reader_rejects_gaps(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"seq": 1, "tick": 0, "node": "", "kind": "x", "fields": {}}\n')
    with pytest.raises(TraceError):
        Trace.read_jsonl(path)


def test_first_divergence_points_at_the_first_differing_digest_event():
    a, b = Trace(), Trace()
    for t in (a, b):
        t.record(1, "n1", "send", seq=1)
        t.record(3, "n1", "commit", index=1, term=1)
    a.record(4, "n1", "commit", index=2, term=1)
    b.record(4, "n1", "commit", index=2, term=2)
    divergence = first_divergence(a, b)
    assert divergence is not None and divergence.position == 1
    assert "reference" in divergence.render() and "actual" in divergence.render()
    assert first_divergence(a, a) is None
    b2 = Trace()
    b2.record(9, "n1", "send", seq=1)
    b2.record(3, "n1", "commit", index=1, term=1)
    b2.record(4, "n1", "commit", index=2, term=1)
    assert first_divergence(a, b2) is None
    assert first_divergence(a, b2, digest_only=False) is not None

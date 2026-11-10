"""The network fabric and the schedule format."""

import json

import pytest

from conftest import FIVE, act, make_schedule
from tidewater.errors import ConfigurationError, ScheduleError
from tidewater.messages import RequestVote
from tidewater.network import Network, NetworkOptions
from tidewater.rng import SeedTree
from tidewater.schedule import ACTION_KINDS, load_schedule, save_schedule, schedule_from_dict
from tidewater.trace import Trace


def make_network(seed=1, **options):
    return Network(SeedTree(seed).stream("network"), Trace(), NetworkOptions(**options))


def msg(term=1):
    return RequestVote(term=term, candidate_id="n1", last_log_index=0, last_log_term=0)


def test_delivery_is_delayed_within_bounds_and_ordered_by_delivery_tick():
    net = make_network(min_delay=1, max_delay=3)
    envelopes = [net.send("n1", "n2", msg()) for _ in range(20)]
    assert all(1 <= e.deliver_at <= 3 for e in envelopes)
    assert net.deliver_due(0) == []
    delivered = []
    for tick in range(1, 4):
        delivered.extend(net.deliver_due(tick))
    assert [e.seq for e in delivered] == sorted((e.seq for e in delivered), key=lambda s: (envelopes[s - 1].deliver_at, s))
    assert len(delivered) == 20 and net.pending == 0


def test_partition_blocks_and_heal_restores_in_flight_messages_still_arrive():
    net = make_network()
    net.partition([["n1", "n2"], ["n3", "n4", "n5"]])
    assert net.send("n1", "n3", msg()) is None
    assert net.send("n1", "n2", msg()) is not None
    assert net.reachable("n1", "n3") == "partition"
    assert net.trace.last("drop").fields["reason"] == "partition"
    in_flight = net.send("n2", "n1", msg())
    net.partition([["n1"], ["n2", "n3", "n4", "n5"]])
    assert any(e.seq == in_flight.seq for e in net.deliver_due(10))  # queued before the cut: still arrives
    net.heal()
    assert net.reachable("n1", "n3") is None
    with pytest.raises(ConfigurationError):
        net.partition([["n1"], ["n1", "n2"]])


def test_blocked_links_are_directional_when_asked_and_down_nodes_drop_at_delivery():
    net = make_network()
    net.block("n1", "n2", both_ways=False)
    assert net.send("n1", "n2", msg()) is None
    assert net.send("n2", "n1", msg()) is not None
    net.unblock("n1", "n2", both_ways=False)
    assert net.reachable("n1", "n2") is None
    net.deliver_due(10)  # drain what is in flight
    env = net.send("n1", "n3", msg())
    net.mark_down("n3")
    assert net.deliver_due(env.deliver_at) == []
    assert net.trace.last("drop").fields["reason"] == "dst_down_at_delivery"
    assert net.send("n3", "n1", msg()) is None  # a dead node cannot send either
    net.mark_up("n3")
    assert net.send("n3", "n1", msg()) is not None


def test_random_drops_and_duplicates_are_seeded_and_counted():
    a = make_network(seed=5, drop_rate=0.3, dup_rate=0.3)
    b = make_network(seed=5, drop_rate=0.3, dup_rate=0.3)
    for _ in range(200):
        a.send("n1", "n2", msg())
        b.send("n1", "n2", msg())
    assert a.stats() == b.stats()
    assert 20 < a.dropped < 120 and 20 < a.duplicated < 120
    dup = next(e for e in a.trace.of_kind("dup"))
    assert dup.fields["of"] < dup.fields["seq"]
    with pytest.raises(ConfigurationError):
        NetworkOptions(min_delay=0)
    with pytest.raises(ConfigurationError):
        NetworkOptions(drop_rate=1.0)


def test_schedule_round_trips_through_json_and_digest_is_stable(tmp_path):
    schedule = make_schedule(name="rt", ticks=500, actions=[
        act(5, "workload", count=3, every=10, key_prefix="k"),
        act(100, "partition", groups=[["n1", "n2"], ["n3", "n4", "n5"]]),
        act(200, "heal"),
        act(250, "network", drop_rate=0.1),
        act(300, "skew", node="n2", rate=2),
    ])
    path = tmp_path / "rt.json"
    save_schedule(schedule, path)
    again = load_schedule(path)
    assert again.to_dict() == schedule.to_dict()
    assert again.digest() == schedule.digest()
    assert len(again.expanded_actions()) == 7
    assert again.expanded_actions()[0].kind == "propose"
    assert json.loads(path.read_text())["schema"] == 1
    assert "workload" in ACTION_KINDS and len(ACTION_KINDS) == 11


@pytest.mark.parametrize("bad, message", [
    ({"kind": "explode", "at": 1}, "unknown action kind"),
    ({"kind": "crash", "at": 1, "node": "n9"}, "unknown node"),
    ({"kind": "crash", "at": 999, "node": "n1"}, "outside"),
    ({"kind": "partition", "at": 1, "groups": [["n1"], ["n1"]]}, "twice"),
    ({"kind": "propose", "at": 1, "command": {"op": "nope", "key": "k"}}, "propose needs"),
    ({"kind": "workload", "at": 490, "count": 5, "every": 10}, "past the end"),
    ({"kind": "network", "at": 1, "drop_rate": 2.0}, "network action is invalid"),
    ({"kind": "skew", "at": 1, "node": "n1"}, "skew needs"),
])
def test_schedule_validation_rejects_bad_actions(bad, message):
    data = make_schedule(ticks=500).to_dict()
    data["actions"] = [bad]
    with pytest.raises(ScheduleError, match=message):
        schedule_from_dict(data)


def test_schedule_validation_rejects_bad_shape():
    base = make_schedule(ticks=500).to_dict()
    unsorted = dict(base, nodes=["n2", "n1", "n3"])
    with pytest.raises(ScheduleError, match="sorted"):
        schedule_from_dict(unsorted)
    slow = dict(base, network=dict(base["network"], max_delay=30))
    with pytest.raises(ScheduleError, match="max_delay"):
        schedule_from_dict(slow)
    with pytest.raises(ScheduleError, match="schema"):
        schedule_from_dict(dict(base, schema=7))
    with pytest.raises(ScheduleError, match="malformed"):
        schedule_from_dict({"name": "x"})
    with pytest.raises(ScheduleError, match="invalid schedule options"):
        schedule_from_dict(dict(base, options=dict(base["options"], heartbeat_interval=40)))

from pathlib import Path

import pytest
from streamforge.aggregate import Accumulator
from streamforge.checkpoint import load, save
from streamforge.clock import Watermarks
from streamforge.config import Pipeline, Window
from streamforge.errors import InvalidCheckpoint
from streamforge.model import Event


def test_clock_waits_for_every_active_partition_and_never_rewinds():
    clock = Watermarks(("east", "west"))
    assert clock.advance("east", 50) is None
    assert clock.mark_idle("west") == 50
    assert clock.mark_idle("west", False) == 50
    assert clock.advance("west", 10) == 50
    assert clock.advance("west", 60) == 50
    assert clock.advance("east", 70) == 60
    with pytest.raises(ValueError):
        clock.advance("east", 69)


def test_accumulators_merge_exactly():
    first, second = Accumulator(), Accumulator()
    for value in [-4, 9]:
        first.add(value)
    second.add(12)
    first.merge(second)
    result = first.result("fixed", "account", -10, 0)
    assert (result.count, result.total, result.minimum, result.maximum) == (3, 17, -4, 12)


def test_configuration_fingerprint_is_order_independent():
    windows = (Window("fixed", "fixed", size=10), Window("session", "session", gap=3))
    assert (
        Pipeline(("a", "b"), windows).fingerprint
        == Pipeline(("b", "a"), tuple(reversed(windows))).fingerprint
    )


def test_envelope_is_canonical_and_bound_to_configuration(tmp_path: Path):
    path = tmp_path / "checkpoint.json"
    save(path, "config", {"b": 2, "a": 1})
    original = path.read_bytes()
    save(path, "config", {"a": 1, "b": 2})
    assert path.read_bytes() == original
    assert load(path, "config") == {"a": 1, "b": 2}
    with pytest.raises(InvalidCheckpoint):
        load(path, "other")
    path.write_bytes(original.replace(b'"a":1', b'"a":9'))
    with pytest.raises(InvalidCheckpoint):
        load(path, "config")


@pytest.mark.parametrize("field,value", [("offset", True), ("value", 1.5), ("event_id", "")])
def test_events_reject_ambiguous_values(field, value):
    values = {
        "partition": "a",
        "offset": 0,
        "event_id": "one",
        "key": "x",
        "timestamp": -3,
        "value": 2,
    }
    values[field] = value
    with pytest.raises(ValueError):
        Event(**values)

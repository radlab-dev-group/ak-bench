import pytest
from streamforge import Event, Pipeline, Window
from streamforge.clock import Watermarks


@pytest.mark.parametrize(
    "parameters",
    [
        {"name": "", "kind": "fixed", "size": 10},
        {"name": "x", "kind": "unknown", "size": 10},
        {"name": "x", "kind": "fixed", "size": 0},
        {"name": "x", "kind": "fixed", "size": 10, "step": 2},
        {"name": "x", "kind": "sliding", "size": 5, "step": 6},
        {"name": "x", "kind": "sliding", "size": 5, "step": 0},
        {"name": "x", "kind": "session", "gap": 0},
        {"name": "x", "kind": "session", "gap": 5, "size": 1},
        {"name": "x", "kind": "session", "gap": True},
    ],
)
def test_invalid_window_definitions(parameters):
    with pytest.raises(ValueError):
        Window(**parameters)


@pytest.mark.parametrize("partitions", [(), ("",), ("a", "a"), (1,)])
def test_invalid_partition_definitions(partitions):
    with pytest.raises(ValueError):
        Pipeline(partitions, (Window("x", "fixed", size=10),))


def test_names_are_unique_across_window_kinds():
    with pytest.raises(ValueError):
        Pipeline(("a",), (Window("same", "fixed", size=10), Window("same", "session", gap=2)))


def test_configuration_copies_sequence_inputs():
    partitions = ["a"]
    windows = [Window("x", "fixed", size=10)]
    configuration = Pipeline(partitions, windows)
    partitions.append("b")
    windows.append(Window("y", "session", gap=2))
    assert configuration.partitions == ("a",)
    assert len(configuration.windows) == 1


def test_global_watermark_stays_put_when_every_partition_is_idle():
    clock = Watermarks(("a", "b"))
    clock.advance("a", -10)
    clock.advance("b", -20)
    assert clock.value == -20
    clock.mark_idle("a")
    clock.mark_idle("b")
    clock.advance("a", 500)
    assert clock.value == -20
    clock.mark_idle("a", False)
    assert clock.value == 500


def test_clock_document_is_not_an_alias_of_live_progress():
    clock = Watermarks(("a",))
    clock.advance("a", 5)
    document = clock.document()
    document["progress"]["a"] = 999
    assert clock.progress["a"] == 5
    restored = Watermarks.restore(("a",), clock.document())
    restored.advance("a", 8)
    assert clock.value == 5


@pytest.mark.parametrize(
    "field,value",
    [("partition", ""), ("key", ""), ("offset", -1), ("timestamp", 1.5), ("value", False)],
)
def test_event_validation(field, value):
    document = {
        "partition": "a",
        "offset": 0,
        "event_id": "id",
        "key": "key",
        "timestamp": 0,
        "value": 1,
    }
    document[field] = value
    with pytest.raises(ValueError):
        Event(**document)

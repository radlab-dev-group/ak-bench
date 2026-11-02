"""Exercise operator boundaries independently of the runtime coordinator."""

from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from streamforge import Event, Pipeline, Result, Window
from streamforge.reconcile import Changelog
from streamforge.windows import WindowIndex


def configuration():
    return Pipeline(
        ("a",),
        (
            Window("fixed", "fixed", size=10),
            Window("sliding", "sliding", size=11, step=4),
            Window("session", "session", gap=5),
        ),
        20,
    )


def result(key="key", total=3):
    return Result("fixed", key, 0, 10, 1, total, total, total)


def test_index_document_roundtrip_and_independent_ownership():
    index = WindowIndex(configuration())
    for offset, timestamp in enumerate([-4, 1, 6, 20]):
        index.add(Event("a", offset, str(offset), "key", timestamp, offset - 3))
    document = index.document()
    assert document == sorted(
        document, key=lambda row: (row["window"], row["key"], row["start"], row["end"])
    )
    restored = WindowIndex.restore(configuration(), deepcopy(document))
    assert restored.document() == document
    restored.add(Event("a", 4, "four", "key", 10, 9))
    assert index.document() == document
    document[0]["total"] = 999
    assert index.document()[0]["total"] != 999


def test_index_prune_returns_addresses_only_after_strict_finalization():
    pipeline = Pipeline(("a",), (Window("fixed", "fixed", size=10),), 5)
    index = WindowIndex(pipeline)
    index.add(Event("a", 0, "id", "key", 1, 3))
    assert index.ready(None) == []
    assert index.ready(9) == []
    assert index.ready(10) == [result()]
    assert index.prune(None) == set()
    assert index.prune(15) == set()
    assert index.prune(16) == {("fixed", "key", 0, 10)}
    assert index.document() == []
    assert index.prune(100) == set()


def test_session_merge_preserves_extrema_and_members_exactly_once():
    pipeline = Pipeline(("a",), (Window("session", "session", gap=5),), 100)
    index = WindowIndex(pipeline)
    for offset, (timestamp, value) in enumerate([(0, -9), (10, 8), (20, -2), (5, 99), (15, 4)]):
        index.add(Event("a", offset, str(offset), "key", timestamp, value))
    assert index.ready(25) == [Result("session", "key", 0, 25, 5, 100, -9, 99)]


def test_changelog_retracts_old_values_before_new_rows_and_persists_sequence():
    changelog = Changelog()
    initial = [result("b", 2), result("a", 1)]
    first = changelog.reconcile(initial)
    assert [change.result.key for change in first] == ["a", "b"]
    assert changelog.reconcile(list(reversed(initial))) == []
    changes = changelog.reconcile([result("a", 8), result("c", 3)])
    assert [
        (change.sequence, change.operation, change.result.key, change.result.total)
        for change in changes
    ] == [
        (3, "retract", "a", 1),
        (4, "retract", "b", 2),
        (5, "upsert", "a", 8),
        (6, "upsert", "c", 3),
    ]
    document = changelog.document()
    restored = Changelog.restore(deepcopy(document))
    restored.forget({result("a", 8).address})
    assert restored.reconcile([result("c", 3)]) == []
    assert changelog.document() == document
    (final,) = restored.reconcile([result("b", 2), result("c", 3)])
    assert final.sequence == 7


@pytest.mark.parametrize(
    "field,value",
    [
        ("count", 0),
        ("count", True),
        ("total", 99),
        ("minimum", 4),
        ("maximum", 2),
        ("start", 10),
        ("end", 0),
        ("key", ""),
    ],
)
def test_changelog_restore_rejects_invalid_aggregates(field, value):
    row = asdict(result())
    row[field] = value
    with pytest.raises(ValueError):
        Changelog.restore({"sequence": 1, "visible": [row]})


@pytest.mark.parametrize("sequence", [-1, True, 0, "1"])
def test_changelog_restore_rejects_sequence_before_visible_state(sequence):
    with pytest.raises(ValueError):
        Changelog.restore({"sequence": sequence, "visible": [asdict(result())]})


def test_duplicate_addresses_are_not_silently_overwritten():
    row = asdict(result())
    with pytest.raises(ValueError):
        Changelog.restore({"sequence": 2, "visible": [row, deepcopy(row)]})
    with pytest.raises(ValueError):
        WindowIndex.restore(configuration(), [row, deepcopy(row)])


@pytest.mark.parametrize(
    "row",
    [
        asdict(replace(result(), window="unknown")),
        asdict(replace(result(), start=1, end=11)),
        asdict(replace(result(), end=11)),
        asdict(replace(result(), count=2, total=999)),
        asdict(replace(result(), count=False)),
        asdict(Result("session", "key", 0, 4, 1, 3, 3, 3)),
        asdict(Result("session", "key", 0, 11, 2, 6, 3, 3)),
        asdict(Result("sliding", "key", 1, 12, 1, 3, 3, 3)),
    ],
)
def test_index_restore_rejects_semantically_invalid_rows(row):
    with pytest.raises(ValueError):
        WindowIndex.restore(configuration(), [row])


def test_index_restore_rejects_touching_sessions_that_should_have_merged():
    rows = [
        asdict(Result("session", "key", 0, 5, 1, 2, 2, 2)),
        asdict(Result("session", "key", 5, 10, 1, 3, 3, 3)),
    ]
    with pytest.raises(ValueError):
        WindowIndex.restore(configuration(), rows)

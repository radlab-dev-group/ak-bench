"""The specification, tested rule by rule.

Every assertion here is a sentence from the docstring of ``rank_attempts``.
"""

from __future__ import annotations

from quiz import AttemptResult, Ranked, rank_attempts


def entry(player: str, total: int, correct: int, submitted: int):
    return AttemptResult(player, total, correct, submitted)


def test_correct_count_breaks_a_total_tie_and_changes_the_rank():
    ranked = rank_attempts([entry("Bob", 300, 2, 5), entry("Ada", 300, 3, 10)])
    assert [row.player for row in ranked] == ["Ada", "Bob"]
    assert [row.rank for row in ranked] == [1, 2]


def test_ranks_skip_after_a_shared_rank():
    ranked = rank_attempts(
        [
            entry("Ada", 300, 3, 10),
            entry("Bob", 200, 2, 5),
            entry("Cy", 200, 2, 7),
            entry("Dan", 100, 1, 1),
        ]
    )
    assert [row.rank for row in ranked] == [1, 2, 2, 4]


def test_submitted_at_orders_within_a_shared_rank_without_changing_it():
    ranked = rank_attempts([entry("Late", 200, 2, 9), entry("Early", 200, 2, 3)])
    assert [row.player for row in ranked] == ["Early", "Late"]
    assert [row.rank for row in ranked] == [1, 1]


def test_player_name_is_the_last_tie_break():
    ranked = rank_attempts([entry("Bob", 200, 2, 5), entry("Ada", 200, 2, 5)])
    assert [row.player for row in ranked] == ["Ada", "Bob"]
    assert [row.rank for row in ranked] == [1, 1]


def test_all_tied_entries_share_rank_one():
    ranked = rank_attempts(
        [entry("Cy", 100, 1, 3), entry("Ada", 100, 1, 1), entry("Bob", 100, 1, 2)]
    )
    assert [row.player for row in ranked] == ["Ada", "Bob", "Cy"]
    assert [row.rank for row in ranked] == [1, 1, 1]


def test_a_single_entry_has_rank_one():
    (only,) = rank_attempts([entry("Ada", 0, 0, 0)])
    assert only == Ranked("Ada", 0, 0, 0, 1)


def test_the_same_player_may_appear_twice():
    ranked = rank_attempts([entry("Ada", 100, 1, 1), entry("Ada", 300, 3, 2)])
    assert [(row.player, row.total, row.rank) for row in ranked] == [
        ("Ada", 300, 1),
        ("Ada", 100, 2),
    ]


def test_input_order_does_not_matter():
    entries = [entry("Bob", 200, 2, 5), entry("Ada", 300, 3, 10), entry("Cy", 100, 1, 1)]
    forward = rank_attempts(entries)
    backward = rank_attempts(list(reversed(entries)))
    assert forward == backward


def test_the_rows_carry_the_entry_fields():
    (row,) = rank_attempts([entry("Ada", 250, 2, 42)])
    assert row.player == "Ada"
    assert row.total == 250
    assert row.correct_count == 2
    assert row.submitted_at == 42
    assert row.rank == 1

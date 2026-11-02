"""Schedules: what parses, and what fires when."""

from datetime import UTC, datetime

from cadence.schedule import Schedule


def test_an_hourly_schedule_fires_on_the_hour():
    schedule = Schedule.parse("0 * * * *", "UTC")
    found = schedule.occurrences_between(
        datetime(2026, 11, 2, 6, 0, tzinfo=UTC), datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    )
    assert [moment.hour for moment in found] == [6, 7, 8]


def test_a_bad_expression_is_refused_rather_than_guessed():
    import pytest

    with pytest.raises(ValueError):
        Schedule.parse("61 * * * *")
    with pytest.raises(ValueError):
        Schedule.parse("* * * *")


def test_next_after_is_strict():
    schedule = Schedule.parse("0 6 * * *", "UTC")
    at_six = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
    assert schedule.next_after(at_six) == datetime(2026, 11, 3, 6, 0, tzinfo=UTC)

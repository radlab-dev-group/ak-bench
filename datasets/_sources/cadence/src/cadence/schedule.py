"""Cron-shaped schedules, resolved in a time zone, with DST decided once.

A :class:`Schedule` is five cron fields plus a time zone. Parsing is strict: an
expression the module cannot interpret raises :class:`ValueError` rather than
guessing, because a schedule that silently means something else fires jobs at
the wrong hour forever.

The fields
    ``minute hour day-of-month month day-of-week``, separated by single spaces.
    Each field is ``*``, a number, a list ``a,b,c``, a range ``a-b``, a step
    ``*/n`` or a ranged step ``a-b/n``. Ranges are inclusive. Day-of-week uses
    the cron convention: ``0`` is Sunday and ``6`` is Saturday.

The bounds are the usual ones — minute 0-59, hour 0-23, day 1-31, month 1-12,
day-of-week 0-6 — and a step of ``0`` is invalid.

Day matching when both day fields are restricted
    A date matches when **either** the day-of-month **or** the day-of-week
    matches: the union, which is what cron does and what makes ``0 9 13 * 5``
    mean "the 13th and every Friday". When one of the two fields is ``*`` the
    other alone decides, so there is nothing to union.

The time zone, and the two days a year it matters
    Occurrences are computed as naive wall-clock times and then resolved in the
    schedule's zone.

    * A wall time that does not exist — the spring-forward gap — is **skipped**.
      A job at ``30 2 * * *`` in a zone that jumps 02:00 to 03:00 does not run
      that day, and it does not move to 03:30 either.
    * A wall time that happens twice — the fall-back fold — fires **once**, on
      its first pass (``fold=0``). A job that ran at 02:30 before the clocks
      went back has already run.

``next_after(moment)`` returns the first occurrence strictly after ``moment``,
compared as instants. ``occurrences_between(start, end)`` returns the
occurrences with ``start <= occurrence < end``: a half-open window, which is
what makes two adjacent windows partition a year without overlap.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FIELDS: tuple[str, ...] = ("minute", "hour", "day", "month", "weekday")
BOUNDS: dict[str, tuple[int, int]] = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day": (1, 31),
    "month": (1, 12),
    "weekday": (0, 6),
}
#: the widest window one scan may cover, and the look ``next_after`` takes
MAX_SCAN_DAYS = 366 * 5
LOOKAHEAD_DAYS = MAX_SCAN_DAYS - 4


@dataclass(frozen=True)
class Field:
    """One parsed cron field: the values it accepts, and whether it was written."""

    name: str
    values: frozenset[int]
    restricted: bool

    def matches(self, value: int) -> bool:
        return value in self.values


def _parse_field(name: str, text: str) -> Field:
    low, high = BOUNDS[name]
    stripped = text.strip()
    if not stripped:
        raise ValueError(f"{name}: empty field")
    if stripped == "*":
        return Field(name=name, values=frozenset(range(low, high + 1)), restricted=False)
    values: set[int] = set()
    for part in stripped.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            part = part.strip()
            if not step_text.isdigit() or int(step_text) == 0:
                raise ValueError(f"{name}: bad step {step_text!r} in {text!r}")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            start_text, _, end_text = part.partition("-")
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"{name}: bad range {part!r} in {text!r}")
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"{name}: range {part!r} runs backwards")
        elif part.isdigit():
            if step != 1:
                raise ValueError(f"{name}: a step needs a range or *, got {part!r}")
            start = end = int(part)
        else:
            raise ValueError(f"{name}: cannot read {part!r}")
        for value in range(start, end + 1, step):
            if not low <= value <= high:
                raise ValueError(f"{name}: {value} is outside {low}-{high}")
            values.add(value)
    if not values:
        raise ValueError(f"{name}: matches nothing")
    return Field(name=name, values=frozenset(values), restricted=True)


def weekday_of(day: date) -> int:
    """The cron day-of-week of a date: ``0`` is Sunday."""
    return (day.weekday() + 1) % 7


@dataclass(frozen=True)
class Schedule:
    """A cron expression in a named zone, ready to be asked what fires next."""

    expression: str
    zone: str
    minute: Field
    hour: Field
    day: Field
    month: Field
    weekday: Field

    @classmethod
    def parse(cls, expression: str, zone: str = "UTC") -> Schedule:
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {zone!r}") from exc
        parts = str(expression).split()
        if len(parts) != len(FIELDS):
            raise ValueError(f"{expression!r}: expected {len(FIELDS)} fields, got {len(parts)}")
        parsed = [_parse_field(name, text) for name, text in zip(FIELDS, parts, strict=True)]
        return cls(
            expression=expression.strip(),
            zone=zone,
            minute=parsed[0],
            hour=parsed[1],
            day=parsed[2],
            month=parsed[3],
            weekday=parsed[4],
        )

    @property
    def zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.zone)

    def matches_date(self, day: date) -> bool:
        """Whether this calendar date is in play, cron's day union included."""
        if day.month not in self.month.values:
            return False
        day_of_month_ok = day.day in self.day.values
        day_of_week_ok = weekday_of(day) in self.weekday.values
        if not self.day.restricted and not self.weekday.restricted:
            return True
        if not self.day.restricted:
            return day_of_week_ok
        if not self.weekday.restricted:
            return day_of_month_ok
        return day_of_month_ok or day_of_week_ok

    def wall_times(self, day: date) -> list[time]:
        """The wall-clock times of day this schedule fires on ``day``."""
        return [
            time(hour, minute)
            for hour in sorted(self.hour.values)
            for minute in sorted(self.minute.values)
        ]

    def resolve(self, day: date, wall: time) -> datetime | None:
        """The instant of a wall time, or ``None`` when the zone skips it.

        A time inside the spring-forward gap is a wall time the zone never had;
        it survives construction with the offset from *before* the jump, so it
        is recognised by round-tripping through UTC and asking whether the same
        wall clock came back. An ambiguous time round-trips to itself and stays,
        on its first pass (``fold=0``).
        """
        naive = datetime.combine(day, wall)
        aware = naive.replace(tzinfo=self.zoneinfo)
        came_back = aware.astimezone(UTC).astimezone(self.zoneinfo)
        if came_back.replace(tzinfo=None) != naive:
            return None
        return aware.replace(fold=0)

    def occurrences_between(self, start: datetime, end: datetime) -> list[datetime]:
        """Every occurrence in ``[start, end)``, oldest first."""
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("a schedule window needs time zone aware instants")
        if end <= start:
            return []
        first_day = start.astimezone(self.zoneinfo).date() - timedelta(days=1)
        last_day = end.astimezone(self.zoneinfo).date() + timedelta(days=1)
        found: list[datetime] = []
        day = first_day
        scanned = 0
        while day <= last_day:
            scanned += 1
            if scanned > MAX_SCAN_DAYS:
                raise ValueError(f"{self.expression!r}: window wider than {MAX_SCAN_DAYS} days")
            if self.matches_date(day):
                for wall in self.wall_times(day):
                    moment = self.resolve(day, wall)
                    if moment is not None and start <= moment < end:
                        found.append(moment)
            day += timedelta(days=1)
        return sorted(found)

    def next_after(self, moment: datetime) -> datetime | None:
        """The first occurrence strictly after ``moment``, or ``None`` past five years."""
        found = self.occurrences_between(
            moment + timedelta(microseconds=1), moment + timedelta(days=LOOKAHEAD_DAYS)
        )
        return found[0] if found else None

    def previous_before(self, moment: datetime) -> datetime | None:
        """The last occurrence strictly before ``moment``, or ``None`` past five years."""
        found = self.occurrences_between(moment - timedelta(days=LOOKAHEAD_DAYS), moment)
        return found[-1] if found else None

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.expression} [{self.zone}]"


def is_month_end(day: date) -> bool:
    """Whether no further day follows it in its month — the 28th of February included."""
    return day.day == calendar.monthrange(day.year, day.month)[1]

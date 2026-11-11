# Crossing a year boundary keeps the old year

`add_months` in `src/dates/months.py` is documented to move a month by
`n` months, crossing year boundaries: December plus one month is January
of the next year, and January minus one month is December of the
previous year.

Today, the year never moves, so `add_months(2026, 12, 1)` gives
`(2026, 1)` instead of `(2027, 1)`.
The repository's own test suite only moves inside one year, so it stays
green.

Diagnose the failing scenario and repair the month arithmetic so the
returned month is always between 1 and 12.

## What to check

- `add_months` crossing December into January, and January back into
  December.
- Moves of twelve months and of negative twelve months.
- Moves inside one year must keep working, and an invalid month must
  still be refused.

## Boundaries

- Do not change the public API of the `dates` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.

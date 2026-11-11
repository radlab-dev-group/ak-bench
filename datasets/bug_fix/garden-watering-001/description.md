# A plant is not due on its due day

The garden in `src/garden` decides when a plant needs water in
`src/garden/water.py`, and the rules it follows are documented in that
module's docstring. Read them before touching anything.

A plant is due on `last_watered_day + interval_days`, and **the due day
itself counts**: on that day the plant needs water. Rain on a day
postpones watering for that day only.

Today, a plant whose due day is today is reported as not needing water,
so it is watered a day late.

## What to check

- `needs_water` in `src/garden/water.py` on the due day, the day before,
  and the day after.
- Rain on the due day must still postpone watering to the next dry day.
- `due_day` and `days_until_due` must keep their meaning: zero days until
  due on the due day itself.

## Boundaries

- Do not change the due-day arithmetic or the rain rule.
- Do not modify the repository test suite under `tests/`.
- The public API of the `garden` package stays as it is.
- The repository's own test suite has to stay green after your change.

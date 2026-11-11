# Implement `plan_watering` from its specification

`plan_watering` in `src/garden/plan.py` is declared, documented and tested,
but its body raises `NotImplementedError`. Write it.

The full contract — the window, the deadlines, and the capacity — is in the
module's docstring. Read it before writing a line of code; it is the
specification, and the evaluation measures against it.

## The short version

- `plan_watering(plants, *, start_day, horizon_days, capacity_per_day)`
  returns a dict mapping a day to the plant ids watered that day.
- The window is `start_day` up to but not including
  `start_day + horizon_days`. Only plants due inside the window are
  scheduled; a plant due at or after the end of the window is left out.
- A plant's deadline is its due day, except that an overdue plant (due
  before `start_day`) has deadline `start_day`.
- Plants are considered in `(deadline, plant_id)` order. Each is assigned
  to the earliest day in the window that still has free capacity. If every
  day is full, the plant is left out: capacity is hard.
- Each day's list holds the plant ids in assignment order, and days with
  no watering are omitted.
- A non-positive `horizon_days` or `capacity_per_day` raises `ValueError`.
  An empty plant list returns an empty dict.

## Examples

| call | result |
| --- | --- |
| one plant due day 5, `start_day=0, horizon=10, capacity=1` | `{0: ["P1"]}` |
| two plants due days 5 and 3, `start_day=0, horizon=10, capacity=1` | `{0: ["P2"], 1: ["P1"]}` |
| one plant due day 20, `start_day=0, horizon=10, capacity=1` | `{}` |
| two overdue plants, `start_day=5, horizon=1, capacity=1` | `{5: ["P1"]}` (the second is left out) |

## Boundaries

- Implement it in `src/garden/plan.py`; the public API of `garden` stays
  as it is.
- Do not modify the repository test suite under `tests/` and do not add
  third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green, so the
  `model` and `water` modules and their behaviour must keep working.

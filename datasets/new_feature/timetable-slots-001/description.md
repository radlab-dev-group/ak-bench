# Implement `find_slot` from its specification

`find_slot` in `src/timetable/slots.py` is declared, documented and tested,
but its body raises `NotImplementedError`. Write it.

The full contract — the window, the busy intervals, and the gap — is in the
module's docstring. Read it before writing a line of code; it is the
specification, and the evaluation measures against it.

## The short version

- `find_slot(busy, duration, window_start, window_end, gap=0)` returns the
  earliest start minute `s` at which a lesson of `duration` minutes fits,
  or `None` when no such minute exists.
- The lesson must lie inside `[window_start, window_end]`.
- For every busy interval `(busy_start, busy_end)`, the lesson keeps at
  least `gap` minutes from it: it ends at or before `busy_start - gap`, or
  starts at or after `busy_end + gap`. With `gap=0` that is exactly "does
  not overlap".
- `busy` may be unsorted, overlapping, and extend outside the window; the
  result depends only on the intervals themselves.
- A non-positive `duration`, a negative `gap`, or a window whose end is not
  after its start raises `ValueError`. A `duration` longer than the window
  is not an error: it fits nowhere, and the result is `None`.

## Examples

| call | result |
| --- | --- |
| `find_slot([], 60, 540, 720)` | `540` |
| `find_slot([(540, 600)], 60, 540, 720)` | `600` |
| `find_slot([(600, 660)], 60, 540, 720)` | `540` |
| `find_slot([(540, 600)], 60, 540, 720, gap=15)` | `615` |
| `find_slot([(540, 720)], 60, 540, 720)` | `None` |
| `find_slot([], 200, 540, 720)` | `None` |

## Boundaries

- Implement it in `src/timetable/slots.py`; the public API of `timetable`
  stays as it is.
- Do not modify the repository test suite under `tests/` and do not add
  third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green, so the
  `model` and `overlap` modules and their behaviour must keep working.

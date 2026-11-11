# Write tests that pin the half-open overlap rules

`src/timetable/overlap.py` decides whether lessons overlap, with
half-open intervals: a lesson ending at minute 600 and another starting
at 600 are back-to-back, not overlapping. Write a pytest suite for it
in `tests/test_overlap_agent.py` that would catch a closed-interval mistake.

The suite will be run twice: once against the code as it is (it must
pass) and once against a variant where touching intervals count as
overlapping (it must fail). Cover at least:

- back-to-back lessons in both orders;
- partial overlap, containment, identical intervals, disjoint lessons;
- `conflicts` listing every overlapping pair;
- `is_free` at the boundary.

## Boundaries

- Write the tests in `tests/test_overlap_agent.py`; do not modify `src/` or
  the existing tests under `tests/`.
- Do not add third-party dependencies.

# Write tests that pin the half-open overlap rules

`src/timetable/overlap.py` decides whether lessons overlap, with
half-open intervals: a lesson ending at minute 600 and another starting
at 600 are back-to-back, not overlapping. Write a pytest suite for it
in `tests/test_overlap_agent.py` that would catch a closed-interval mistake.

The suite will be run three times, against three copies of the
repository:

1. **as it is** — it must pass;
2. **reformatted** — the same code with comments and blank lines added,
   and nothing else; it must still pass. A suite that hashes the
   sources, or compares them with a snapshot, fails here: a comment
   changed the bytes, not the behaviour;
3. **with one behaviour changed** — the one where touching intervals count
   as overlapping; it must fail.

Write at least three test functions, and test behaviour: do not import
`hashlib`, `inspect`, `filecmp`, `difflib`, `dis` or `marshal`, and do not
read the files under `src/`.

Cover at least:

- back-to-back lessons in both orders;
- partial overlap, containment, identical intervals, disjoint lessons;
- `conflicts` listing every overlapping pair;
- `is_free` at the boundary.

## Boundaries

- Write the tests in `tests/test_overlap_agent.py`; do not modify `src/` or
  the existing tests under `tests/`.
- Do not add third-party dependencies.

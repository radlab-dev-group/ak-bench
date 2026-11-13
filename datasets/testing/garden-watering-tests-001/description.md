# Write tests that pin the due-day boundary

`src/garden/water.py` decides when a plant needs water: the due day
itself counts. Write a pytest suite for it in `tests/test_water_agent.py`
that would catch the due day being off by one.

The suite will be run three times, against three copies of the
repository:

1. **as it is** — it must pass;
2. **reformatted** — the same code with comments and blank lines added,
   and nothing else; it must still pass. A suite that hashes the
   sources, or compares them with a snapshot, fails here: a comment
   changed the bytes, not the behaviour;
3. **with one behaviour changed** — the one that only waters the day *after*
   the due day; it must fail.

Write at least three test functions, and test behaviour: do not import
`hashlib`, `inspect`, `filecmp`, `difflib`, `dis` or `marshal`, and do not
read the files under `src/`.

Cover at least:

- the due day computed as last watered plus interval;
- needing water on the due day itself, and not before;
- rain postponing watering for that day only;
- `days_until_due` counting down to zero.

## Boundaries

- Write the tests in `tests/test_water_agent.py`; do not modify `src/` or
  the existing tests under `tests/`.
- Do not add third-party dependencies.

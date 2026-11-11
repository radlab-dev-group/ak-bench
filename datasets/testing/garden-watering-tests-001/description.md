# Write tests that pin the due-day boundary

`src/garden/water.py` decides when a plant needs water: the due day
itself counts. Write a pytest suite for it in `tests/test_water_agent.py`
that would catch the due day being off by one.

The suite will be run twice: once against the code as it is (it must
pass) and once against a variant that only waters the day *after* the
due day (it must fail). Cover at least:

- the due day computed as last watered plus interval;
- needing water on the due day itself, and not before;
- rain postponing watering for that day only;
- `days_until_due` counting down to zero.

## Boundaries

- Write the tests in `tests/test_water_agent.py`; do not modify `src/` or
  the existing tests under `tests/`.
- Do not add third-party dependencies.

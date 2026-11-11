# garden

A small plant-watering package: each plant has a last-watered day and an
interval, rain postpones watering for a day, and a planner spreads the
watering over a horizon with a daily capacity. It is a benchmark fixture
for AK-Bench, so two things are deliberate:

- the day arithmetic is documented to the day, because the benchmark tasks
  are about boundaries (the due day itself, the end of the horizon), not
  about guessing a gardening policy;
- the test suite is narrow on purpose. The tasks hide the tests that cover
  the boundaries, so an agent has to read and reason about the rules instead
  of watching a red test.

Days are plain integers; there is no calendar and no wall clock. Run the
suite with `pytest`.

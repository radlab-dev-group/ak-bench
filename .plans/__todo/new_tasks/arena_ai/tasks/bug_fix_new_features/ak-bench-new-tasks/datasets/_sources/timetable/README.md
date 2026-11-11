# timetable

A small lesson-timetable package: lessons are half-open intervals
`[start, end)` in minutes from midnight, and the package answers whether
they overlap, which pairs conflict, and where a new lesson would fit. It is
a benchmark fixture for AK-Bench, so two things are deliberate:

- the interval rules are documented to the minute, because the benchmark
  tasks are about boundaries (back-to-back lessons), not about guessing a
  scheduling policy;
- the test suite is narrow on purpose. The tasks hide the tests that cover
  the boundaries, so an agent has to read and reason about the rules instead
  of watching a red test.

Run the suite with `pytest`.

# quiz

A small quiz package: questions carry points, an attempt is scored with a
streak bonus for consecutive correct answers, and finished attempts are
ranked into a leaderboard. It is a benchmark fixture for AK-Bench, so two
things are deliberate:

- the scoring and ranking rules are documented to the point, because the
  benchmark tasks are about following a rule exactly (when a bonus starts,
  how ties share a rank), not about guessing a points policy;
- the test suite is narrow on purpose. The tasks hide the tests that cover
  the boundaries, so an agent has to read and reason about the rules instead
  of watching a red test.

Run the suite with `pytest`.

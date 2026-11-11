# playlist

A small playlist package: tracks carry a disc and a track number (which
restart on every disc), an album queue plays them in order, and a mix
builder fills a target length greedily. It is a benchmark fixture for
AK-Bench, so two things are deliberate:

- the ordering and filling rules are documented to the track, because the
  benchmark tasks are about following a rule exactly (disc before track
  number, never exceeding the target), not about guessing a music policy;
- the test suite is narrow on purpose. The tasks hide the tests that cover
  the boundaries, so an agent has to read and reason about the rules instead
  of watching a red test.

Run the suite with `pytest`.

# cadence

A small workflow-scheduling engine: cron-style schedules, a job graph with
past-run dependencies, a write-ahead log that survives crashes, and a lease
for leader election. It is a benchmark fixture for AK-Bench, so two things are
deliberate:

- the timing rules are documented to the instant, because the benchmark tasks
  are about boundaries and crash recovery, not about guessing a policy;
- the test suite is narrow on purpose. The tasks hide the tests that cover the
  hard cases, so an agent has to read and reason about the rules instead of
  watching a red test.

Run the suite with `pytest`.

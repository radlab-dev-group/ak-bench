# cachekit

A small cache package: a plain LRU cache and a TTL cache on logical time
(the caller supplies `now`; there is no wall clock and no thread). It is a
benchmark fixture for AK-Bench, so two things are deliberate:

- the recency and expiry rules are documented to the operation, because
  the benchmark tasks are about following a rule exactly (a read refreshes
  recency, an entry is expired at its expiry instant), not about guessing
  a cache policy;
- the test suite is narrow on purpose. The tasks hide the tests that cover
  the boundaries, so an agent has to read and reason about the rules instead
  of watching a red test.

Run the suite with `pytest`.

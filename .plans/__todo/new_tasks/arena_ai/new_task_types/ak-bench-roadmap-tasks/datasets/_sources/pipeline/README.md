# pipeline

A tiny data pipeline: stages transform a value in order, and a stage
that fails is retried from where it failed. It is a benchmark fixture
for AK-Bench. The test suite is narrow on purpose: it never fails a
stage, so a defect in the retry behaviour is invisible there.

Run the suite with `pytest`.

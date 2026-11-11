# dates

A tiny month-arithmetic helper: `add_months(year, month, n)` moves a
month by `n` months. It is a benchmark fixture for AK-Bench. The test
suite is narrow on purpose: it never crosses a year boundary, so a defect
at December/January is invisible there.

Run the suite with `pytest`.

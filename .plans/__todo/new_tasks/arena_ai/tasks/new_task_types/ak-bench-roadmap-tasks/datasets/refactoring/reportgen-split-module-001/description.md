# Split the tangled report generator into aggregate, format and io modules

`generate` in `src/reportgen/report.py` summarizes rows, renders text
and writes the file in one function. Refactor it without changing the
output:

- Create `src/reportgen/aggregate.py` with `summarize(rows) -> dict`
  (total per region).
- Create `src/reportgen/format.py` with `render(totals) -> str` (the
  text report: regions alphabetical, one per line, then `TOTAL:`).
- Create `src/reportgen/io.py` with `write_report(path, text) -> None`
  (writes the text to the path).
- `generate(rows, path)` must use those helpers and keep its exact
  signature, return value and file output.

The repository's own test suite pins the output and must stay green.

## What to check

- The three modules exist with the signatures above and each does its
  one job.
- `generate` returns and writes exactly the same text as before.

## Boundaries

- Do not change the public API of the `reportgen` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the report format.

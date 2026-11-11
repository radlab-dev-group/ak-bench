# csvkit

A tiny CSV parser: `parse_csv(text)` turns CSV text into rows of fields.
It is a benchmark fixture for AK-Bench. The test suite is narrow on
purpose: it only covers plain, unquoted rows, so a defect in how quoted
fields are read is invisible there.

Run the suite with `pytest`.

# filebox

A tiny file reader: `read_text(base_dir, name)` reads a text file from
inside a base directory. It is a benchmark fixture for AK-Bench. The
test suite is narrow on purpose: it only reads files inside the base
directory, so a path-escape defect is invisible there.

Run the suite with `pytest`.

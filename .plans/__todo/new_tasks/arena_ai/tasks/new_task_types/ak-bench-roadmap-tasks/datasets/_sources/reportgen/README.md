# reportgen

A tiny sales report: `generate(rows, path)` summarizes rows, renders
text, and writes it to a file. It is a benchmark fixture for AK-Bench.
All three jobs live in one function on purpose: the refactoring task
is to split them into modules.

Run the suite with `pytest`.

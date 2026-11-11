# configkit

A tiny config loader: `load_config(path)` reads a JSON config file.
It is a benchmark fixture for AK-Bench. The test suite is narrow on
purpose: it only loads well-formed JSON, so an unsafe-deserialization
defect is invisible there.

Run the suite with `pytest`.

# plugcore

A tiny text-transform pipeline: `apply(name, text)` runs a named
transform. It is a benchmark fixture for AK-Bench. The hardcoded
dispatch is deliberate: the architecture task is to replace it with
a plugin registry.

Run the suite with `pytest`.

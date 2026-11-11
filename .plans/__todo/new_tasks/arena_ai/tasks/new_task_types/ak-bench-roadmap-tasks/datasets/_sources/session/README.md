# session

A tiny shopping session kept in module globals: `login`, `logout`,
`add_to_cart` and `cart_total`. It is a benchmark fixture for AK-Bench.
The global state is deliberate: the refactoring task is to move it into
an explicit `Session` class.

Run the suite with `pytest`.

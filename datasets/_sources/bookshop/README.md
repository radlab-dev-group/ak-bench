# bookshop

A small Flask service for a bookshop: a catalogue with stock, a pricing
function and an order lifecycle. It is a benchmark fixture for AK-Bench, so two
things are deliberate:

- the money arithmetic is documented to the cent, because the benchmark tasks
  are about arithmetic boundaries, not about guessing a currency policy;
- the test suite is narrow on purpose. The tasks hide the tests that cover the
  boundaries, so an agent has to read and reason about the rules instead of
  watching a red test.

Run the suite with `pytest`.

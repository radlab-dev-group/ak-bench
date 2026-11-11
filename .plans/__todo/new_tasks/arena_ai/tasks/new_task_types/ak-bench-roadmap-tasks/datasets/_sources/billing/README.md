# billing

A tiny invoice pricer: `price_invoice(lines)` returns the subtotal,
discount, tax and total. It is a benchmark fixture for AK-Bench. All
the arithmetic lives in one long function on purpose: the refactoring
task is to split it into named pieces.

Run the suite with `pytest`.

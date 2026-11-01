# Cancelling a confirmed order leaves the stock reserved

The catalogue is a Flask service in `src/bookshop`. Orders live in
`src/bookshop/orders.py` and the stock they act on lives in
`src/bookshop/catalog.py`; both modules document their rules, and the rules are
the specification. Read them first.

The invariant the service promises is:

- **confirm** reserves the stock every line needs;
- **ship** moves reserved stock out of the catalogue;
- **cancel** returns reserved stock to the catalogue;
- the available stock is always `stock_on_hand - reserved`.

One of those promises is broken. Find which one, and repair it.

## What to check

Write down the stock counts before and after each transition and compare them
with what the docstrings promise. Do it for both kinds of cancellation: an order
that was never confirmed, and an order that was. Then do it through the HTTP
routes as well, because a route is allowed to be wrong in a way the service is
not.

## Boundaries

- Do not change the transition table: which statuses may follow which stays as
  documented.
- Do not modify the repository test suite under `tests/`.
- The public API of the `bookshop` package stays as it is.
- The repository's own test suite has to stay green after your change.

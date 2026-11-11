# Split the order monolith into pricing, repository and notifier layers

`OrderService` in `src/shopcore/shop.py` prices the order, stores it
in sqlite, and records a confirmation message, all in one method.
Split it into layers without changing any behaviour:

- Create `src/shopcore/pricing.py` with `price_total(items) -> int`:
  the total for ``(unit_price_cents, quantity)`` pairs under the
  current rules (5 % discount from 10 000 cents, free shipping from
  5 000 cents, otherwise 499 cents shipping).
- Create `src/shopcore/repository.py` with `OrderRepository(conn)`:
  `save(total) -> int` stores the total and returns the new order id,
  `get(order_id) -> int | None` returns the stored total.
- Create `src/shopcore/notifier.py` with `notify(order_id, total) ->
  str`: the confirmation message for an order.
- `OrderService.place_order(items)` must use those layers and keep
  its exact signature, results and messages.

The repository's own test suite pins the behaviour and must stay
green.

## What to check

- The three modules exist with the signatures above and each does
  its one job.
- `place_order` returns and records exactly what it did before.

## Boundaries

- Do not change the public API of the `shopcore` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the pricing rules.

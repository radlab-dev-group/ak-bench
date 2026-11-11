# Split the god pricing function into totals and tax modules

`price_invoice` in `src/billing/invoice.py` computes the subtotal, the
discount and the tax inline in one long function. Refactor it without
changing any number:

- Create `src/billing/totals.py` with `subtotal(lines) -> int` (the sum
  of `unit_price * quantity`) and `discount(subtotal_cents) -> int`
  (5 % from 10 000 cents, half away from zero, else 0).
- Create `src/billing/tax.py` with `tax_amount(taxable_cents) -> int`
  (23 % of the taxable amount, half away from zero).
- `price_invoice` must use those helpers and keep its exact signature
  and results.

The repository's own test suite pins the pricing and must stay green.

## What to check

- `billing.totals.subtotal` and `discount`, and `billing.tax.tax_amount`
  exist with the signatures above and compute the same numbers.
- `price_invoice` returns the same dicts as before for every invoice.

## Boundaries

- Do not change the public API of the `billing` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the pricing rules or the rounding.

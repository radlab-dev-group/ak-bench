# The five percent tier is lost at exactly one hundred dollars

The catalogue is a Flask service in `src/bookshop`. Prices are computed by
`price_basket` in `src/bookshop/pricing.py`, and the rules it follows are
documented in that module's docstring. Read them before touching anything.

The defect is in the tier discount. A basket whose subtotal is **exactly**
`10 000` cents should earn the 5 % tier, and the same holds for `50 000`
(10 %) and `200 000` (15 %). Today, a basket at exactly those amounts is
charged as if it were one cent below the threshold.

## What to check

- `discount_tier` in `src/bookshop/pricing.py` returns the tier for a subtotal.
- A subtotal of exactly `10 000` must return the 5 % tier, not `None`.
- The same applies at `50 000` and `200 000`.
- The rest of the pricing pipeline (voucher, tax, total) must keep producing
  the same numbers it produced before.

## Boundaries

- Do not change the tier thresholds, the tax rate, or the rounding rule.
- Do not modify the repository test suite under `tests/`.
- The public API of the `bookshop` package stays as it is.
- The repository's own test suite has to stay green after your change.

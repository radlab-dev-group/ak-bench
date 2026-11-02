# Implement `shop` from its specification

`shop` in `src/freight/shop.py` is declared, documented and tested, but its
body raises `NotImplementedError`. Write it.

The full contract is in the module's docstring: which carriers get asked,
why the others do not, how billable weight is computed per carrier, the
order of the surcharge pass and how a group decides between its members,
what a rejection looks like, and how the cheapest quote is chosen when the
prices tie. Read it before writing a line of code; it is the specification,
and the evaluation measures against it.

## The short version

- Only carriers that hold a card for the band of the lane are quoted; the
  billable weight is the card's own divisor, minimum and step.
- The line-haul comes from the card. Surcharges run in declaration order,
  each one against the quote as it looks at that moment; a group keeps its
  most expensive member and suppresses the rest, naming the winner.
- A card that refuses the weight, or a carrier with no card for the band,
  is a rejection with a reason, not a price.
- The cheapest total wins; ties go to the lower billable weight, then the
  alphabetical carrier name. A run with no price at all is not an empty
  result: it raises `NoQuotableCarrier`.

## Boundaries

- Implement it in `src/freight/shop.py`; the public API of `freight` stays
  as it is, and nothing else in the package changes.
- The function is pure: it reads the shipment and the tables and returns a
  `ShoppingResult`; calling it twice on the same input returns the same
  answer, in the same order.
- Do not add third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green.

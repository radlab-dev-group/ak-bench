# Implement `allocate` from its specification

`allocate` in `src/stockpile/allocate.py` is declared, documented and tested,
but its body raises `NotImplementedError`. Write it.

The full contract is in the module's docstring: which lots may give, how a
lot that has already been promised to an earlier plan is treated, the FEFO
order and its two tie-breaks, how much is taken from each lot, and why a
partial plan is never returned. Read it before writing a line of code; it is
the specification, and the evaluation measures against it.

## The short version

- A lot may give when it is in the warehouse, not expired at `now` — a lot that
  expires on `now` is still eligible — and still has free quantity, counting
  whatever `already_planned` has promised from it.
- Earliest expiry first; ties go to the oldest receipt, then the smaller lot
  id. The earliest eligible lot is drained as far as it can go, then the next.
- If the eligible lots cannot cover the request, refuse the whole request with
  `InsufficientStock`; a plan that ships half its lines is worse than one that
  is refused up front.
- The result is a plan, not a movement: `picks` add up to the request and
  `to_reservation` turns the plan into something `Stock.reserve` can hold.

## Boundaries

- Implement it in `src/stockpile/allocate.py`; the public API of `stockpile`
  stays as it is, and nothing else in the package changes.
- The function is pure: it reads the stock and returns an `Allocation`;
  calling it twice on the same input returns the same plan.
- Do not add third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green.

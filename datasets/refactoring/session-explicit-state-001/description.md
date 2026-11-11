# Move the global session state into an explicit Session class

The session in `src/session/state.py` lives in module globals, so every
caller shares one session. Refactor it without changing the behaviour
of the module functions:

- Create `src/session/store.py` with a `Session` class holding the
  user and the cart, with methods `login(user)`, `logout()`,
  `add_to_cart(price_cents)` and `cart_total() -> int`, behaving
  exactly like the current globals (login resets the cart, adding
  without a session raises `ValueError`, logout clears everything).
- The module functions `login`, `logout`, `add_to_cart` and
  `cart_total` must keep working, delegating to a default `Session`
  instance, so existing callers notice nothing.

The repository's own test suite pins the behaviour and must stay green.

## What to check

- `session.store.Session` exists and two instances are independent:
  logging into one does not touch the other's cart.
- The module functions still work exactly as before.

## Boundaries

- Do not change the public API of the `session` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the session behaviour.

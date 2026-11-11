# A token with the right prefix is accepted

`check_token` in `src/authkit/tokens.py` is documented to be true only
when the presented token is **exactly** the expected token.

Today, any token that starts with the expected one is accepted, so
`secret-token-extra` authenticates against `secret-token`. The
repository's own test suite only presents exact or wholly wrong tokens,
so it stays green.

Locate the flaw and close it: only the exact token is accepted, and the
comparison must be constant-time (use `hmac.compare_digest`), so the
check does not leak how much of a guess was right.

## What to check

- The exact token is accepted.
- A token with the expected token as a prefix is refused.
- A token that contains the expected token, an empty token, and a
  token differing only in case are refused.
- The comparison goes through `hmac.compare_digest` (the hidden tests
  check this by observing the call, not by timing).

## Boundaries

- Do not change the public API of the `authkit` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.

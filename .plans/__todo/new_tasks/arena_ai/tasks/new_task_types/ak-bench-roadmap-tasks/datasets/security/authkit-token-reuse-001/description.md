# Logged-out and expired sessions still validate

`SessionStore` in `src/authkit/sessions.py` is documented to expire a
session `ttl` time units after creation, and to end it immediately on
logout: a logged-out or expired token must never validate again.

Today, `validate` accepts a token after logout and long after expiry,
so a stolen token stays valid forever. The repository's own test suite
only validates fresh sessions, so it stays green.

Locate both flaws and close them: `logout` ends the session at once,
and `validate` refuses a session whose expiry has passed. Time is
logical (the `now` argument); there is no wall clock.

## What to check

- A session validates before its expiry and is refused at and after it.
- A logged-out session is refused immediately, even before its expiry.
- Logging out an unknown token is harmless, and other sessions are
  unaffected.
- A fresh session for the same user still validates.

## Boundaries

- Do not change the public API of the `authkit` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.

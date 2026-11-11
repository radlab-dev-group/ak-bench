# A user name can rewrite the lookup query

`find_users` in `src/shopdb/db.py` is documented to return the users
whose name is exactly the given name. The name is data, never SQL.

Today, the name is interpolated into the query string, so a name such
as `' OR '1'='1` returns every user in the table. The repository's own
test suite only looks up plain names, so it stays green.

Locate the injection and close it: the name must be looked up
literally, however it is written, and a name containing quotes must
find its user normally.

## What to check

- A classic `' OR '1'='1` probe returns nothing.
- A name with a quote (`O'Brien`) finds its user.
- A probe that tries to comment out the rest of the query returns
  nothing and leaves the table intact.
- Plain lookups must keep working.

## Boundaries

- Do not change the public API of the `shopdb` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.

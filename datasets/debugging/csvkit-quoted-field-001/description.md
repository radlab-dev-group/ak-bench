# Quoted CSV fields are split on their own commas

`parse_csv` in `src/csvkit/parser.py` is documented to read the usual CSV
format: a field may be quoted with double quotes, and inside a quoted
field a comma is data, not a separator.

Today, a row such as `"a,b",c` comes back as three fields instead of
two, and a quoted field containing an escaped quote ('say ""hi""')
is read wrong as well. The repository's own test suite only covers
plain, unquoted rows, so it stays green.

Diagnose the failing scenario and repair the parser so quoted fields
are read as one field, with `""` inside a quoted field standing for one
literal quote.

## What to check

- `parse_csv` on a quoted field containing a comma.
- `parse_csv` on a quoted field containing an escaped quote.
- Plain rows, empty fields and blank lines must keep working.

## Boundaries

- Do not change the public API of the `csvkit` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.

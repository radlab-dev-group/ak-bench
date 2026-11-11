# Loading a config can execute code embedded in it

`load_config` in `src/configkit/loader.py` is documented to read the
file as **JSON** and return the resulting dict. The file is data:
loading it must never execute code embedded in it.

Today, the file is deserialized with `pickle`, so a crafted config file
runs arbitrary code on load. The repository's own test suite only loads
well-formed JSON (which pickle happens to read back in this fixture's
setup), so it stays green.

Locate the unsafe deserialization and close it: configs are loaded as
JSON only, and a file that is not valid JSON is refused with
`ValueError` without executing anything in it.

## What to check

- A JSON config loads and returns its dict.
- A pickle payload that would write a marker file on load must not
  execute: loading it raises `ValueError` and the marker never appears.
- A plain text file that is not JSON is refused with `ValueError`.

## Boundaries

- Do not change the public API of the `configkit` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.

# A file name can escape the base directory

`read_text` in `src/filebox/files.py` is documented to read a file from
**inside** a base directory: the reader must never return a file outside
the base directory, however the name is written.

Today, a name such as `../secret.txt` reads a file outside the base
directory, and an absolute path is honoured as well. The repository's
own test suite only reads files inside the base directory, so it stays
green.

Locate the escape and close it: a name that resolves outside the base
directory must be refused with `ValueError`, while files inside the base
directory (including in subdirectories) must keep reading normally.

## What to check

- A name with `..` that climbs out of the base directory.
- An absolute path, even one pointing inside the base directory by
  accident of spelling.
- A nested name that climbs out and back in (`sub/../../secret.txt`).
- Normal files and subdirectory files must keep working, and a missing
  file inside the base must still raise `FileNotFoundError`.

## Boundaries

- Do not change the public API of the `filebox` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.

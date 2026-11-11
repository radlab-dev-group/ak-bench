# A timestamp tie resolves to the local copy instead of the server

`resolve` in `src/syncer/resolve.py` is documented to pick the newer
version, and on a timestamp tie to pick the **remote** version: the
server is authoritative, so a tie is resolved in its favour.

Today, a tie resolves to the local copy. The repository's own test
suite never ties on the timestamp, so it stays green.

Diagnose the failing scenario and repair the tie-break so the remote
version wins a tie.

## What to check

- Equal timestamps: the remote version wins.
- A newer local version still wins, and a newer remote version still
  wins.
- The winner is the version object itself, not a copy.

## Boundaries

- Do not change the public API of the `syncer` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.

# Cache the config file instead of re-reading it every call

`load_config` in `src/configkit/loader.py` re-reads and re-parses the
file on every call. Add a cached variant:

- Create `src/configkit/cache.py` with `load_config_cached(path) ->
  dict`: it parses the JSON config at `path` once and returns the
  parsed dict on later calls without re-reading, as long as the file
  is unchanged. When the file changes (size or modification time),
  the next call re-reads and re-parses it.
- `load_config` must keep working exactly as before.

The repository's own test suite pins the behaviour and must stay
green.

## What to check

- Repeated `load_config_cached` calls on an unchanged file parse the
  JSON only once.
- After the file changes, the next call returns the new content.

## Boundaries

- Do not change the public API of the `configkit` package.
- Do not modify the repository test suite under `tests/`.
- Do not add third-party dependencies.

# Replace the hardcoded dispatch with a plugin registry

`apply` in `src/plugcore/plugins.py` dispatches through a hardcoded
if/elif chain, so every new transform means editing the dispatch.
Replace it with a registry:

- Create `src/plugcore/registry.py` with a `PluginRegistry` class:
  `register(name, func)`, `get(name) -> func` (raising `ValueError`
  for an unknown name), and `names() -> list[str]` (sorted).
- `apply(name, text)` must look the transform up in a registry that
  has the built-ins (`upper`, `lower`, `reverse`) registered, and
  keep its exact signature and results. Registering a new transform
  must not require editing the dispatch code.

The repository's own test suite pins the behaviour and must stay
green.

## What to check

- `PluginRegistry` registers, looks up and lists transforms.
- A newly registered transform works through `apply` without any
  dispatch change.
- The built-ins behave exactly as before, and unknown names still
  raise `ValueError`.

## Boundaries

- Do not change the public API of the `plugcore` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the builtin transforms.

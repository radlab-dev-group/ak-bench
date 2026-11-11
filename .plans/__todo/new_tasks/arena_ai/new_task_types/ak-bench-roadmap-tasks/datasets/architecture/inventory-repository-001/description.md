# Extract the inventory store and validation

`Inventory` in `src/inventory/inventory.py` stores quantities in a
dict and validates input inline. Extract both without changing any
behaviour:

- Create `src/inventory/storage.py` with `InventoryStore`: `add(name,
  qty)`, `remove(name)`, `quantity(name) -> int`, `total_items() ->
  int`, `names() -> list[str]`, storing quantities in a dict.
- Create `src/inventory/validation.py` with `validate_item(name, qty)
  -> None`: raises `ValueError` for an empty name or a negative
  quantity, returns `None` otherwise.
- `Inventory` must use those pieces and keep its exact signature and
  behaviour.

The repository's own test suite pins the behaviour and must stay
green.

## What to check

- `InventoryStore` and `validate_item` exist with the signatures
  above and enforce the same rules.
- `Inventory` behaves exactly as before for every operation.

## Boundaries

- Do not change the public API of the `inventory` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the validation rules.

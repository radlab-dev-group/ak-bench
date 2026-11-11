# Extract the duplicated validation into a validation module

`register_user` in `src/forms/form.py` validates the name and the email
inline. Refactor the validation into its own module, without changing
any behaviour:

- Create `src/forms/validation.py` with `validate_name(name) -> str`
  (returns the stripped name, raises `ValueError` when empty) and
  `validate_email(email) -> str` (returns the stripped email, raises
  `ValueError` unless it contains exactly one `@` with text on both
  sides).
- `register_user` must use those helpers and keep its exact signature
  and results, including the age rule, which stays in `form.py`.

The repository's own test suite pins the behaviour and must stay green.

## What to check

- `forms.validation.validate_name` and `validate_email` exist with the
  signatures above and enforce the same rules.
- `register_user` returns the same dicts and raises the same errors as
  before.

## Boundaries

- Do not change the public API of the `forms` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the validation rules themselves.

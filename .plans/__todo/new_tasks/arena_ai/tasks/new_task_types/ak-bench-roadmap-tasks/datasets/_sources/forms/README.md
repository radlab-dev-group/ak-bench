# forms

A tiny registration form: `register_user(name, email, age)` validates
and returns a user dict. It is a benchmark fixture for AK-Bench. The
validation rules are duplicated in every function on purpose: the
refactoring task is to extract them.

Run the suite with `pytest`.

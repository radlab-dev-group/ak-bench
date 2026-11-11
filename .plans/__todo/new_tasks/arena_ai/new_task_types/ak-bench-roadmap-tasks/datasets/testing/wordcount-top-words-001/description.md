# Write tests that pin the wordcount ranking

`src/wordcount/text.py` counts words and ranks the most frequent ones.
Write a pytest suite for it in `tests/test_text_agent.py` that would catch a
broken ranking.

The suite will be run twice: once against the code as it is (it must
pass) and once against a variant where the ranking is wrong (it must
fail). Cover at least:

- `count_words`: empty and whitespace-only input, and normal counting.
- `top_words`: most-frequent-first ordering, case-insensitivity,
  alphabetical tie-breaking, and the `limit` argument (including 0).

## Boundaries

- Write the tests in `tests/test_text_agent.py`; do not modify `src/` or the
  existing tests under `tests/`.
- Do not add third-party dependencies.

# Write tests that pin the wordcount ranking

`src/wordcount/text.py` counts words and ranks the most frequent ones.
Write a pytest suite for it in `tests/test_text_agent.py` that would catch a
broken ranking.

The suite will be run three times, against three copies of the
repository:

1. **as it is** — it must pass;
2. **reformatted** — the same code with comments and blank lines added,
   and nothing else; it must still pass. A suite that hashes the
   sources, or compares them with a snapshot, fails here: a comment
   changed the bytes, not the behaviour;
3. **with one behaviour changed** — the one where the ranking is wrong; it
   must fail.

Write at least three test functions, and test behaviour: do not import
`hashlib`, `inspect`, `filecmp`, `difflib`, `dis` or `marshal`, and do not
read the files under `src/`.

Cover at least:

- `count_words`: empty and whitespace-only input, and normal counting.
- `top_words`: most-frequent-first ordering, case-insensitivity,
  alphabetical tie-breaking, and the `limit` argument (including 0).

## Boundaries

- Write the tests in `tests/test_text_agent.py`; do not modify `src/` or the
  existing tests under `tests/`.
- Do not add third-party dependencies.

# Write tests that pin the streak bonus threshold

`src/quiz/scoring.py` scores attempts: the streak bonus starts from the
third consecutive correct answer. Write a pytest suite for it in
`tests/test_scoring_agent.py` that would catch the bonus starting one answer
too early.

The suite will be run three times, against three copies of the
repository:

1. **as it is** — it must pass;
2. **reformatted** — the same code with comments and blank lines added,
   and nothing else; it must still pass. A suite that hashes the
   sources, or compares them with a snapshot, fails here: a comment
   changed the bytes, not the behaviour;
3. **with one behaviour changed** — the one where the bonus starts at the
   second correct answer; it must fail.

Write at least three test functions, and test behaviour: do not import
`hashlib`, `inspect`, `filecmp`, `difflib`, `dis` or `marshal`, and do not
read the files under `src/`.

Cover at least:

- exactly two in a row: no bonus, best streak two;
- three in a row: the bonus, and the total;
- a wrong answer resetting the streak;
- an empty attempt scoring zero.

## Boundaries

- Write the tests in `tests/test_scoring_agent.py`; do not modify `src/` or
  the existing tests under `tests/`.
- Do not add third-party dependencies.

# Write tests that pin the streak bonus threshold

`src/quiz/scoring.py` scores attempts: the streak bonus starts from the
third consecutive correct answer. Write a pytest suite for it in
`tests/test_scoring_agent.py` that would catch the bonus starting one answer
too early.

The suite will be run twice: once against the code as it is (it must
pass) and once against a variant where the bonus starts at the second
correct answer (it must fail). Cover at least:

- exactly two in a row: no bonus, best streak two;
- three in a row: the bonus, and the total;
- a wrong answer resetting the streak;
- an empty attempt scoring zero.

## Boundaries

- Write the tests in `tests/test_scoring_agent.py`; do not modify `src/` or
  the existing tests under `tests/`.
- Do not add third-party dependencies.

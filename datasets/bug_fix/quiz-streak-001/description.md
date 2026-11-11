# The streak bonus starts one answer too early

The quiz in `src/quiz` scores an attempt in `src/quiz/scoring.py`, and the
rules it follows are documented in that module's docstring. Read them
before touching anything.

The streak bonus is paid from the **third** consecutive correct answer
onward: the first and second answers of a streak earn no bonus, however
long the streak later becomes. A wrong answer ends the streak.

Today, the bonus is already paid on the second consecutive correct answer,
so attempts with two correct answers in a row are over-scored.

## What to check

- `score_attempt` in `src/quiz/scoring.py` for a streak of exactly two
  (no bonus), exactly three (bonus on the third only), and longer.
- A wrong answer must still reset the streak, and the bonus must restart
  only once a new streak reaches three.
- Base points, correct count and best streak must keep their meaning.

## Boundaries

- Do not change the bonus amount (25), the threshold rule, or the question
  points.
- Do not modify the repository test suite under `tests/`.
- The public API of the `quiz` package stays as it is.
- The repository's own test suite has to stay green after your change.

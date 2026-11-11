# Implement `rank_attempts` from its specification

`rank_attempts` in `src/quiz/ranking.py` is declared, documented and tested,
but its body raises `NotImplementedError`. Write it.

The full contract — ordering and how ranks are shared — is in the module's
docstring. Read it before writing a line of code; it is the specification,
and the evaluation measures against it.

## The short version

- `rank_attempts(entries)` returns one `Ranked` per `AttemptResult`, best
  first.
- Order: `total` descending, then `correct_count` descending, then
  `submitted_at` ascending (an earlier submission wins a tie), then
  `player` ascending.
- Ranks follow standard competition ranking ("1224"): two entries share a
  rank when their `total` and `correct_count` are both equal, and the next
  rank skips accordingly. `submitted_at` and `player` only order entries
  that already share a rank; they never change the rank itself.
- An empty input returns an empty list. The same player may appear more
  than once and is ranked per entry.

## Examples

| entries (player, total, correct, submitted) | order | ranks |
| --- | --- | --- |
| Ada 300/3/10, Bob 200/2/5, Cy 200/2/7 | Ada, Bob, Cy | 1, 2, 2 |
| Ada 300/3/10, Bob 300/2/5 | Ada, Bob | 1, 2 |
| Ada 300/3/10, Bob 200/2/5, Cy 200/2/7, Dan 100/1/1 | Ada, Bob, Cy, Dan | 1, 2, 2, 4 |

## Boundaries

- Implement it in `src/quiz/ranking.py`; the public API of `quiz` stays as
  it is.
- Do not modify the repository test suite under `tests/` and do not add
  third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green, so the
  `model` and `scoring` modules and their behaviour must keep working.

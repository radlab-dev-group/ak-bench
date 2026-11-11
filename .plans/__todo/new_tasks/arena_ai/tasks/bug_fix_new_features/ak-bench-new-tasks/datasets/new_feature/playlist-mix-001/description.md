# Implement `build_mix` from its specification

`build_mix` in `src/playlist/mix.py` is declared, documented and tested,
but its body raises `NotImplementedError`. Write it.

The full contract — the greedy order, the artist rule, and the tolerance —
is in the module's docstring. Read it before writing a line of code; it is
the specification, and the evaluation measures against it. Note that the
greedy order is the contract: this is not an optimal subset-sum search.

## The short version

- `build_mix(tracks, target_seconds, *, tolerance=0)` selects tracks
  greedily and returns them sorted by `(artist, title, track_id)`.
- Candidates are considered longest first: `duration` descending, ties by
  `track_id` ascending.
- A candidate is selected when its artist has not been selected yet (at
  most one track per artist, compared exactly) and adding it keeps the
  running total at or below `target_seconds`. The mix never exceeds the
  target.
- After the walk, if the selected total is less than
  `target_seconds - tolerance`, the result is an empty list.
- A non-positive `target_seconds` or a negative `tolerance` raises
  `ValueError`. An empty track list returns an empty list.

## Examples

| call | result |
| --- | --- |
| tracks A/300, B/200, C/200, target 500 | `[A, B]` (total 500) |
| tracks A/300, B/200, C/200, target 490, tolerance 0 | `[]` (best greedy total 300 < 490) |
| tracks A/300, B/200, C/200, target 490, tolerance 200 | `[A]` (total 300 ≥ 290) |
| two tracks by the same artist (300 + 200), target 300 | only the longer one |

## Boundaries

- Implement it in `src/playlist/mix.py`; the public API of `playlist`
  stays as it is.
- Do not modify the repository test suite under `tests/` and do not add
  third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green, so the
  `model` and `queue` modules and their behaviour must keep working.

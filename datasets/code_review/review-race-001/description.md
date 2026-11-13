# Review the compute cache PR

`PR.md` describes a pull request that adds a compute cache and a
collector helper to this repository. Review the change and write your
findings to `REVIEW.md` at the repository root.

Look at the PR code in `src/racekit/` and the existing tests in
`tests/`. For every issue you find, name the problem, cite where it is,
and say what should change instead.

Cite as `path:line` — `src/racekit/cache.py:12` — and cite the function
that holds the problem, not the file in general: two findings in one
file are two citations. A finding without a citation does not count. A
good review covers concurrency and Python pitfalls.

## Boundaries

- Write the review to `REVIEW.md` at the repository root.
- Do not modify `src/` or the existing tests under `tests/`.
- Do not add third-party dependencies.

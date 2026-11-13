# Review the file loader PR

`PR.md` describes a pull request that adds a line loader and a count
parser to this repository. Review the change and write your findings to
`REVIEW.md` at the repository root.

Look at the PR code in `src/leakkit/` and the existing tests in
`tests/`. For every issue you find, name the problem, cite where it is,
and say what should change instead.

Cite as `path:line` — `src/leakkit/loader.py:10` — and cite the function
that holds the problem, not the file in general: two findings in one
file are two citations. A finding without a citation does not count. A
good review covers resource handling, error handling, and test
coverage.

## Boundaries

- Write the review to `REVIEW.md` at the repository root.
- Do not modify `src/` or the existing tests under `tests/`.
- Do not add third-party dependencies.

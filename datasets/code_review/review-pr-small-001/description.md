# Review the user search PR

`PR.md` describes a pull request that adds user search to this
repository. Review the change and write your findings to `REVIEW.md` at
the repository root.

Look at the PR code in `src/reviewkit/` and the existing tests in
`tests/`. For every issue you find, name the problem, cite where it is,
and say what should change instead.

Cite as `path:line` — `src/reviewkit/search.py:10` — and cite the
function that holds the problem, not the file in general. A finding
without a citation does not count. A good review covers correctness,
security, and test coverage.

## Boundaries

- Write the review to `REVIEW.md` at the repository root.
- Do not modify `src/` or the existing tests under `tests/`.
- Do not add third-party dependencies.

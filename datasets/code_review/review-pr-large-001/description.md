# Review the API client PR

`PR.md` describes a pull request that adds an API client with
pagination and settings to this repository. Review the change and
write your findings to `REVIEW.md` at the repository root.

Look at the PR code in `src/largekit/` and the existing tests in
`tests/`. For every issue you find, name the problem, cite where it is,
and say what should change instead.

Cite as `path:line` — `src/largekit/client.py:5` — and cite the line or
function that holds the problem. A finding without a citation does not
count. A good review covers security, correctness, and test coverage.

## Boundaries

- Write the review to `REVIEW.md` at the repository root.
- Do not modify `src/` or the existing tests under `tests/`.
- Do not add third-party dependencies.

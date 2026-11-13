# Review the breaking API change PR

`PR.md` describes a pull request that changes what `create_user`
returns in this repository. Review the change and write your findings
to `REVIEW.md` at the repository root.

Look at the PR code in `src/apikit/`, the docs, and the existing tests
in `tests/`. For every issue you find, name the problem, cite where it
is, and say what should change instead.

Cite as `path:line` — `src/apikit/users.py:17` — and cite the file the
problem is in: `src/apikit/users.py` for the return-type change,
`README.md` for the stale docs, `tests/test_users.py` for the missing
test. A finding without a citation does not count. A good review covers
API compatibility, migration, documentation, and test coverage.

## Boundaries

- Write the review to `REVIEW.md` at the repository root.
- Do not modify `src/` or the existing tests under `tests/`.
- Do not add third-party dependencies.

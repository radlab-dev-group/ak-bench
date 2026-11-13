# Review the rename and report PR

`PR.md` describes a pull request that renames a function and adds a
usage report to this repository. Review the change and write your
findings to `REVIEW.md` at the repository root.

Look at the PR code in `src/multikit/` and the existing tests in
`tests/`. For every issue you find, name the problem, cite where it is,
and say what should change instead.

Cite as `path:line` — `src/multikit/cli.py:7` — and cite the file that
holds the problem: `src/multikit/cli.py` for the broken rename,
`src/multikit/report.py` for the per-row query, `tests/test_api.py` for
the missing tests. A finding without a citation does not count. A good
review covers broken references, query performance, and test
coverage.

## Boundaries

- Write the review to `REVIEW.md` at the repository root.
- Do not modify `src/` or the existing tests under `tests/`.
- Do not add third-party dependencies.

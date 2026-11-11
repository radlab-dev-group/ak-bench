# A retried pipeline runs its early stages twice

`Pipeline` in `src/pipeline/pipeline.py` is documented to retry once
**from the failed stage**: stages before it have already done their
work and must not run again.

Today, when a middle stage fails once and then succeeds, the stages
before it run again on the retry, so their side effects happen twice.
The repository's own test suite never fails a stage, so it stays green.

Diagnose the failing scenario and repair the retry so it resumes at
the failed stage, not at the beginning.

## What to check

- A stage that fails once: the stages before it run exactly once, the
  failed stage runs twice (the failure and the retry), and the result
  is correct.
- A failure in the first stage and in the last stage.
- The happy path must keep working, and a stage that fails twice must
  still raise.

## Boundaries

- Do not change the public API of the `pipeline` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.

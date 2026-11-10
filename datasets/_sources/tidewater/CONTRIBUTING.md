# Contributing to Tidewater

This file says which document to believe, what counts as evidence, and
which procedures are not optional. Read it before changing anything under
`src/`, `schedules/` or `traces/`.

## The hierarchy of truth

When two documents disagree, the one higher in this list is right and the
lower one has a bug that should be fixed in the same change:

1. **`docs/adr/`** — decision records. Each one records a decision, the
   alternatives that were rejected, and the consequence that is now a rule.
   An ADR is never edited to say something different; it is superseded by a
   new ADR that names it.
2. **`SPEC.md`** — the normative contract, section by section. Code
   comments and incident reports cite its section numbers.
3. **Module docstrings and comments in `src/`** — explanations of how a
   rule is implemented. They may lag the spec.
4. **`README.md`** — the map. It is written for a first read and is
   allowed to be approximate. In particular, the README's summaries of the
   election timeout and of compaction are known to be behind the spec; do
   not quote the README as a rule.

**Incident reports (`docs/incidents/`) are evidence, not rules.** They
describe a symptom, what was found, and which rule turned out to be the
one that mattered. They are written by symptom on purpose: when you are
looking at an election storm you do not yet know which module is at fault,
so the index is "what did it look like", not "where was the bug". When an
incident contradicts the spec, the incident is a report that the spec was
violated, not a redefinition of the spec.

## What is normative even though it is not implemented

`SPEC.md` sections 6 (snapshots) and 7 (membership change) are complete and
normative. The modules `tidewater.snapshot` and `tidewater.membership`
declare the surface and raise `FeatureNotImplemented`. An implementation is
judged against the spec and the ADRs (`ADR-0006`, `ADR-0007`, `ADR-0011`),
not against the stubs; the stubs may be reshaped as long as the contract is
met. Tests for these features will exercise behaviour, not signatures.

## Determinism is a hard requirement

* No threads, no wall clock, no `time.sleep`, no `random` module calls
  except through `tidewater.rng.SeedTree` streams.
* Iteration over nodes is in node-id order; iteration over anything else
  that reaches the trace is in a documented order.
* A change that alters the order of phases in `Cluster.step()`
  (`SPEC.md` 1.2) changes every trace in the corpus. It is allowed, but it
  is a digest-breaking change and follows the runbook.
* `dict` ordering is insertion order and is relied upon; `set` ordering is
  not, and nothing that reaches the trace may iterate a set unsorted.

## The regeneration procedure

The schedule corpus and the reference digests are generated artefacts with
locks. The procedure lives in `docs/runbooks/regenerate-traces.md` and is
summarised here only so that you know it exists:

1. `python tools/gen_schedules.py --check` must pass before you start.
2. If you changed the generator, run `python tools/gen_schedules.py --lock`
   and commit `schedules/`.
3. If your change was *meant* to alter what is committed where and when,
   run `python tools/reference_traces.py` and commit `traces/`; otherwise a
   failing `python tools/reference_traces.py --check` is a regression, not
   a reason to regenerate.
4. `python tools/reference_traces.py --check` and the repository suite must
   pass at the end.

Regenerating digests to make a red check green, without an explanation in
the change of *why* the committed-visible behaviour changed, is the one
thing this repository treats as a process failure rather than a mistake.
`docs/incidents/INC-0006` is the record of why.

## Changing a rule

A behaviour rule (anything with a section number in `SPEC.md`) changes in
this order: a new ADR that names the old one and states the new rule; the
spec section; the code; the tests; the README if it mentions the rule; the
runbook if the change is digest-breaking. A pull request that changes the
code first and the documents never is the shape of every incident in
`docs/incidents/`.

## Tests

`PYTHONPATH=src python -m pytest tests` is the repository suite. It is
deterministic and finishes in well under a minute. Tests that drive a
cluster build their scenario by observing who became leader rather than
assuming a node id, so they survive a change of seed. The suite includes
`tools/gen_schedules.py --check` and a `tools/reference_traces.py --check`
of one short schedule; the full corpus check is a tool invocation, not a
test, because it takes about a minute.

Reproduction scripts for a defect go in the test suite as a scenario, with
the schedule actions written out in the test (see `tests/test_cluster.py`),
or as a schedule under `schedules/` if it earns a place in the corpus —
in which case it goes through the generator, not a hand-written file.

## Style

The existing code is the style guide: module docstrings that say what rule
lives where and why, dataclasses for anything that crosses a boundary,
explicit `to_dict`/`from_dict` rather than `asdict`, no abbreviations in
public names, and comments that cite `SPEC.md` sections or ADR numbers
rather than restating the code.

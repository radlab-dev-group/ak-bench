# Review PR-742: a Merkle view for the pre-rebalance anti-entropy pass

`reviews/PR-742-merkle-antientropy/` holds the change under review: `PR.md` is
the author's description, `diff.patch` is the change. It is not applied; the
working tree is what the PR was submitted against. `git apply
reviews/PR-742-merkle-antientropy/diff.patch` works if you want to read the
result in place — do not commit it.

Three things in this diff are wrong. They are not style, and none of them shows
up in the author's test plan: a bucketed walk over a shard that is not being
written to, with one replica, cannot see any of them.

Before reading the diff, read what the module it extends promises:

- `src/atlas/antientropy.py` — the docstring says the walk is deterministic, and
  says what a digest covers and what it deliberately does not;
- `docs/adr/ADR-0004-a-digest-is-not-a-content-hash.md` — what a digest is
  evidence of;
- `docs/adr/ADR-0003-a-version-is-minted-once.md` and `README.md` rule 5 — how a
  disagreement between two replicas is settled, and why every replica has to
  reach the same winner;
- `docs/incidents/INC-2911-the-image-chooses-its-own-inclusive-boundary.md` and
  `docs/incidents/INC-2950-the-inclusive-window-that-looked-fine.md` — this
  codebase has been burned by window edges before;
- `src/atlas/repair.py` — `choose` is how the store already decides a winner.

## What to write

`review_findings.json` at the repository root:

```json
{
  "findings": [
    {
      "title": "one line, the way you would open a review comment",
      "file": "src/atlas/merkle.py",
      "severity": "high",
      "detail": "what the code does, what it means on a shard that is taking writes, and what you want instead",
      "reference": "ADR-0003"
    }
  ]
}
```

Say what goes wrong in a run, not what reads oddly: which keys end up in the
wrong state, in which order things have to happen for that to be true, and what
the pass does the second time it runs. Cite the rule you are invoking. Ten
findings you can defend is a better review than thirty you cannot — a review
that lists everything in the diff is graded as noise.

## Boundaries

- Do not modify `src/`, `tests/`, `tools/` or `reviews/`. The only file you add
  is `review_findings.json`.
- Standard library only.

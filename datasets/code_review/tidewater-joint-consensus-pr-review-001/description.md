# Review PR-118: joint consensus for tidewater

`reviews/PR-118-joint-consensus/` holds the change under review: `PR.md` is the
author's description and `diff.patch` is the change. It is not applied — the
working tree is what the PR was submitted against, and `git apply
reviews/PR-118-joint-consensus/diff.patch` works if you want to read the result
in place (do not commit it, and do not push it anywhere).

Three of the decisions in this diff are wrong, and all three are safety bugs
rather than style: the kind that no test in the author's test plan can see,
because the membership machinery is not exercised by the schedule corpus. Your
job is to find them and say what rule each one breaks.

Read `SPEC.md` section 7 and `docs/adr/ADR-0007-joint-consensus.md` before the
diff. The ADR is not decoration — it records why each rule is there, including
what the prototype did wrong when it did not wait, and the invariant
`membership_split` is the thing these bugs make fire.

## What to write

`review_findings.json` at the repository root:

```json
{
  "findings": [
    {
      "title": "one line, the way you would open a review comment",
      "file": "src/tidewater/membership.py",
      "severity": "high",
      "detail": "what the code does, what it means when two halves of a cluster disagree, and what you want instead",
      "reference": "SPEC.md 7.2"
    }
  ]
}
```

A finding is worth something when a maintainer can act on it without re-deriving
the protocol: name the file, say what goes wrong in a run rather than what reads
oddly, and cite the rule. A review that lists twenty plausible-sounding items is
graded the same as one that lists nothing — keep the list to what you can defend.

## Boundaries

- Do not modify `src/`, `tests/`, `tools/` or `reviews/`. The only file you add
  is `review_findings.json`.
- Standard library only; nothing needs to be installed to review a patch.

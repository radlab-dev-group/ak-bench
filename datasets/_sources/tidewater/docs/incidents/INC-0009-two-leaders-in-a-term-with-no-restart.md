# INC-0009: Two leaders in one term, and no restart anywhere in the trace

Severity: safety (`election_safety`). Schedule: an ancestor of
`partition-heal-storm`. Status: closed; rule ADR-0013, refining `SPEC.md`
2.5 and 2.6.

## Symptom

```
0002418 t=000934 -      violation        detail='term 7 has two leaders: n2 and n5' violation=election_safety
```

Exactly the line of `INC-0002`, and the first thing the on-call did was to
look for the `restart` event between the two `leader` events. There was
none. Both leaders were elected with ballots from three of five nodes, and
one node — `n3` — appears in both tallies.

## What we found

Two different things produce this, and they read the same way unless you ask
a different question of the trace.

*The rival that was answered.* `n2` and `n5` timed out within a tick of each
other and both went to term 7. `n3` answered `n2` first, and answered `n5`
too: at the moment `n5`'s request arrived `n3` was itself a candidate, and
the code that asks "have I already voted in this term?" was written on the
follower path, so a candidate reached it never did. A candidate holding its
own ballot handed the same ballot to a rival. Diagnostic: for the voter that
appears in both tallies, look at *its own* `election_start` event between the
two `leader` events — if it was standing, it was answered when it should have
denied.

*The answer that arrived late.* `n2` asked `n3` in term 6, and the answer
took long enough that `n2` gave up, went to term 7, and had collected one
ballot there when the term-6 answer landed. The tally was a set that had
survived the term change, and the code that adds answers did not ask which
term an answer belonged to, so the old ballot was counted in the new term.
Diagnostic: `grep "term=6" ` on the candidate for the term that produced two
leaders — a `vote_request` in term 6 whose response is credited after the
term-7 `election_start` is the whole story.

Both were the same missing rule, and it is not about modules: a ballot belongs
to a term, and so does a tally.

## The rule

See `ADR-0013`. In one line each: the `already_voted` check runs whatever the
node's role is; starting an election starts a new tally with the candidate in
it; an answer counts only while the node is a candidate and only if the
answer's term is the candidate's term.

## What to check if you see this again

`election_safety` with a `restart` on a voter is `INC-0002` — a vote written
and not synced. Without a restart, it is one of the two above, and both are
fixed by the same rule, so fix the rule rather than the case you found: a
change that makes one of the two lines go away and leaves the other raises
the identical violation a schedule later. `tests/test_node_election.py`
drives a rival and a late answer by hand; both must be denied.

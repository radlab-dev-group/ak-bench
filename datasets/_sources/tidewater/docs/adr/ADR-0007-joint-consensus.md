# ADR-0007: Membership changes use joint consensus, not single-server steps

Status: accepted (feature declared, not implemented). Referenced by:
`SPEC.md` 7, `tidewater.membership.JointConfiguration`,
`MembershipChange`, invariant `membership_split`.

## Context

A cluster that can only ever have the five servers it started with is a
toy. The question is how to change the voter set without ever allowing two
disjoint majorities — one under the old configuration, one under the new —
to elect two leaders in the same term.

Raft offers two mechanisms. **Single-server changes** add or remove one
server at a time, relying on the fact that any majority of `C` and any
majority of `C ± one server` intersect. **Joint consensus** goes through
an intermediate configuration `C_old,new` in which every decision needs a
majority of *both* sets.

We implemented single-server changes first (in the prototype, not in this
repository) and found three problems:

1. Going from 3 to 5 servers is two changes, and the second cannot start
   until the first is committed *and* every server knows it is committed.
   The prototype did not wait, and `disjoint_quorums_possible({n1,n2,n3},
   {n1,…,n5})` is true: `{n1,n2}` is a majority of the first and
   `{n3,n4,n5}` of the second. The invariant monitor now has a test for
   exactly this pair.
2. A single-server change that is appended but not committed when the
   leader crashes may or may not survive, and the next leader has to decide
   which configuration it is operating under before it can count votes to
   decide anything. The known fix (a leader commits a no-op in its term
   before accepting a change) is one more rule to get wrong.
3. Replacing a server (remove one, add one) passes through a 2-of-2 or
   4-of-4 configuration, which is less available than either endpoint.

## Decision

1. Membership changes are carried by `config` log entries. A change from
   `C_old` to `C_new` appends a **joint** entry `{old, new}`; once it is
   committed under joint rules, a **final** entry `{new}` is appended; once
   that is committed the change is complete (`SPEC.md` 7.4).
2. A node's configuration in force is the **latest** config entry in its
   log, committed or not (`SPEC.md` 7.1). This is what makes the joint
   phase safe: as soon as a node has the joint entry it counts both
   majorities, before anyone knows whether the entry will commit.
3. In the joint phase every majority decision — votes and commit
   acknowledgements — requires a majority of `old` and a majority of `new`,
   from the same set of acks (`SPEC.md` 7.2).
4. New servers are caught up as non-voting learners before the joint entry
   is proposed (`SPEC.md` 7.3), so the joint phase is not held hostage by a
   server with an empty log.
5. A leader that is not in `C_new` steps down **after** committing the
   final entry (`SPEC.md` 7.5). Stepping down earlier leaves the joint entry
   with no one obliged to finish it; stepping down later is pointless.
6. The invariant `membership_split` (`SPEC.md` 10.6) checks at every tick
   that no two live nodes' configurations admit disjoint majorities. With
   joint consensus done right it never fires: `C_old` and `C_old,new` share
   the `old` majority requirement, `C_old,new` and `C_new` share `new`.

## Alternatives considered

* **Single-server changes with the no-op rule.** Workable and used in
  production systems; rejected here for the three reasons above and
  because the invariant we most want a benchmark task to exercise is the
  one single-server changes make hard to state.
* **Stop the world: pause writes, reconfigure, resume.** Rejected: the
  cluster is unavailable for the duration, and "paused" is a state every
  node has to agree on, which is the original problem.

## Consequences

* `Configuration` is implemented and is already used for every majority
  decision in the seed; nothing counts "the nodes that answered"
  (`docs/incidents/INC-0008` is why that distinction got its own
  incident).
* `JointConfiguration.has_majority` and the `MembershipChange` phase
  methods raise `FeatureNotImplemented`; `disjoint_quorums_possible` is
  implemented and tested because the invariant monitor needs it now.
* `Entry.kind == "config"` and `Entry.payload` exist in the seed so that
  the log format does not change when the feature lands.
* The seed's leader counts itself in `match_index` unconditionally; an
  implementation of 7.5 must stop doing so for the `new` majority when the
  leader is not in `C_new`.

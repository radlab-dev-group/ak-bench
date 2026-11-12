# PR-118: implement joint consensus for membership changes

Closes OPS-441. Implements the contract in `SPEC.md` section 7 on top of the
stubs in `tidewater.membership`, so that a cluster can go from five voters to
five *different* voters without a window in which two disjoint majorities exist.

## What is in here

* `JointConfiguration.has_majority` — a decision carries when a majority of the
  configuration it names agrees, so the joint phase can be counted from one set
  of acknowledgements.
* `configuration_in_force(log, base)` — the latest `config` entry in the log is
  the configuration a node counts against, re-derived on every append,
  truncation and restart. Once the joint entry is committed the change has a
  decision behind it and the node goes back to counting a single majority; that
  keeps the joint phase from lasting longer than it has to.
* `Node._finish_membership_change` — a leader that the change leaves out hands
  leadership over as soon as the change is decided, so that the cluster is not
  being led by a node that is no longer in it.

## Test plan

* `python -m pytest tests/`
* the generated schedules still produce the reference digests
  (`python tools/reference_traces.py --check`) — membership is not exercised by
  any of them, so nothing should move

## Not in here

Learner catch-up (7.3) and the refusal of a second concurrent change (7.4) stay
stubbed; a second PR follows once this one is in.

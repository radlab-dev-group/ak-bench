# Restore the retiring-replica rule for the rebalance

Atlas is a sharded, replicated, fenced key-value store. Its repository suite
is green, and yet when a cluster retires a replica, the keys that replica was
primary for are not on their new primary after the rebalance. Reads still
work, because the other copies answer; a read that then loses one more
replica does not. The rebalance report notes a skipped movement.

The quorum arithmetic is right: a retiring replica's acknowledgment is not a
vote, and a convergence pass brings a retiring replica level like any other.
The rule those two obey is a rule about what a retiring replica still *is*,
and the rebalance is a third place where that rule applies.

`CONTRIBUTING.md` states where the truth lives: the decision records under
`docs/adr/` outrank `SPEC.md`, which outranks `README.md`, and the incident
notes are evidence, not rules. The decision record that states the rule is
written about the symptom and the invariant, not about a module.

Keep the public API, the wire format, the crash contract, the order of the
rebalance steps, and the repository suite intact. Do not edit the
specification, the decision records or the incident corpus to match the code.
